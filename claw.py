import time
import random
import board
import busio
import displayio
import terminalio
import digitalio
import neopixel
from adafruit_display_text import label
import i2cdisplaybus
import adafruit_displayio_ssd1306
import adafruit_adxl34x
import pwmio

# CONFIG
SCREEN_WIDTH = 128
SCREEN_HEIGHT = 64

CLAW_WIDTH = 40
CLAW_Y1_BASE = 14
CLAW_Y2_BASE = 24
CLAW_Y3_BASE = 36

DROP_STEPS = 10
DROP_STEP_PIXELS = 3

ACCEL_MIN = -4.0
ACCEL_MAX = 4.0

# Accelerometer calibration + filtering
ACCEL_CALIB_SAMPLES = 200
ACCEL_ALPHA = 0.2

offset_x = 0.0
filtered_x = 0.0

BALL_WIDTH = 18
BALL_Y = 60

# MEDIUM mode settings
MEDIUM_MAX_BALLS = 3
MEDIUM_BALL_MIN_LIFE = 1.0
MEDIUM_BALL_MAX_LIFE = 3.0

# HARD mode settings
HARD_BASE_SPEED = 0.7
HARD_SPEED_STEP = 0.25

# Pins
ROT_BTN_PIN = board.D0
ROT_A_PIN = board.D8
ROT_B_PIN = board.D9
LED_PIN = board.D1
NUM_LEDS = 3

# MULTIPLAYER SETTINGS
PLAYER_WIDTH = 8
PLAYER_Y = 52
MP_ROUND_TIME = 120.0  # 2 minutes
MP_HIT_POINTS = 3      # Points for hitting dodger
MP_MISS_POINTS = 1     # Points for dodger when you miss

# Buzzer
buzzer = pwmio.PWMOut(board.D3, frequency=2000, duty_cycle=0, variable_frequency=True)

def beep(freq=2000, duration=0.08):
    buzzer.frequency = freq
    buzzer.duty_cycle = 32768
    time.sleep(duration)
    buzzer.duty_cycle = 0

# Menu options - Easy, Medium, Hard, Multiplayer
MENU_OPTIONS = ["EASY", "MEDIUM", "HARD", "MULTIPLAYER"]

# Level data (for single-player modes)
LEVEL_DATA = [
    (30.0, 3), (30.0, 4), (30.0, 5), (25.0, 5), (25.0, 6),
    (20.0, 6), (20.0, 7), (15.0, 7), (15.0, 8), (12.0, 8),
]

def sfx_hit():
    beep(2400, 0.06)

def sfx_miss():
    beep(500, 0.35)

def sfx_game_over():
    beep(400, 0.15)
    beep(300, 0.15)
    beep(200, 0.2)

def sfx_level_up():
    beep(1500, 0.05)
    beep(1800, 0.05)
    beep(2200, 0.07)

def sfx_mp_hit():
    """Multiplayer hit sound - matches single-player"""
    beep(2400, 0.06)

def sfx_mp_miss():
    """Multiplayer miss sound - matches single-player"""
    beep(500, 0.35)

def map_range(x, in_min, in_max, out_min, out_max):
    if x < in_min:
        x = in_min
    if x > in_max:
        x = in_max
    return out_min + (out_max - out_min) * (x - in_min) / (in_max - in_min)

# Hardware init
displayio.release_displays()
i2c = busio.I2C(board.SCL, board.SDA)

display_bus = i2cdisplaybus.I2CDisplayBus(i2c, device_address=0x3C)
display = adafruit_displayio_ssd1306.SSD1306(display_bus, width=SCREEN_WIDTH, height=SCREEN_HEIGHT)

accelerometer = adafruit_adxl34x.ADXL345(i2c)
accelerometer.range = adafruit_adxl34x.Range.RANGE_2_G

# Calibrate accelerometer
print("Calibrating accelerometer...")
offset_sum = 0.0
for i in range(ACCEL_CALIB_SAMPLES):
    x, y, z = accelerometer.acceleration
    offset_sum += x
    time.sleep(0.01)

offset_x = offset_sum / ACCEL_CALIB_SAMPLES
filtered_x = 0.0
print("Calibration done, offset_x =", offset_x)

# Rotary button
rot_btn = digitalio.DigitalInOut(ROT_BTN_PIN)
rot_btn.switch_to_input(pull=digitalio.Pull.UP)
last_btn_state = rot_btn.value

# Rotary encoder
rot_a = digitalio.DigitalInOut(ROT_A_PIN)
rot_a.switch_to_input(pull=digitalio.Pull.UP)
rot_b = digitalio.DigitalInOut(ROT_B_PIN)
rot_b.switch_to_input(pull=digitalio.Pull.UP)
rot_last_state = rot_a.value

# NeoPixel
pixels = neopixel.NeoPixel(LED_PIN, NUM_LEDS, brightness=0.3, auto_write=True)

# UART for multiplayer (TX->D6, RX->D7)
try:
    uart = busio.UART(tx=board.D6, rx=board.D7, baudrate=115200, timeout=0.01)
    uart_available = True
    print("UART initialized for multiplayer")
except Exception as e:
    uart_available = False
    print("UART not available:", e)

# Display group
splash = displayio.Group()
display.root_group = splash

# Game state variables
in_menu = True
menu_index = 0
game_mode = None  # "EASY", "MEDIUM", "HARD", "MULTIPLAYER"

current_level_index = 0
time_limit = 0.0
target_hits = 0
hits_remaining = 0
round_start_time = 0.0
game_state = "PLAYING"
lives = 3

medium_balls = []
hard_balls = []

# Multiplayer variables
player_x = SCREEN_WIDTH // 2
last_aim_sent = 0.0
AIM_SEND_INTERVAL = 0.03
claw_dropping = False
mp_score_shooter = 0
mp_score_dodger = 0
mp_round_start = 0.0

# UI Labels
title_label = label.Label(terminalio.FONT, text="", color=0xFFFFFF)
title_label.anchor_point = (0.5, 0.0)
title_label.anchored_position = (SCREEN_WIDTH // 2, 0)
splash.append(title_label)

level_label = label.Label(terminalio.FONT, text="", color=0xFFFFFF)
level_label.anchor_point = (0.0, 0.0)
level_label.anchored_position = (0, 0)
splash.append(level_label)

timer_label = label.Label(terminalio.FONT, text="", color=0xFFFFFF)
timer_label.anchor_point = (0.0, 0.0)
timer_label.anchored_position = (0, 10)
splash.append(timer_label)

hits_label = label.Label(terminalio.FONT, text="", color=0xFFFFFF)
hits_label.anchor_point = (1.0, 0.0)
hits_label.anchored_position = (SCREEN_WIDTH - 2, 0)
splash.append(hits_label)

message_label = label.Label(terminalio.FONT, text="", color=0xFFFFFF)
message_label.anchor_point = (0.5, 0.5)
message_label.anchored_position = (SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2)
splash.append(message_label)

# Health bar functions
def update_health_bar():
    for i in range(NUM_LEDS):
        if i < lives:
            pixels[i] = (0, 255, 0)
        else:
            pixels[i] = (255, 0, 0)

def update_mp_health_bar():
    """Show score comparison in multiplayer"""
    diff = mp_score_shooter - mp_score_dodger
    
    if diff >= 6:
        pixels[0] = (0, 255, 0)
        pixels[1] = (0, 255, 0)
        pixels[2] = (0, 255, 0)
    elif diff >= 3:
        pixels[0] = (0, 255, 0)
        pixels[1] = (0, 255, 0)
        pixels[2] = (0, 0, 0)
    elif diff > 0:
        pixels[0] = (0, 255, 0)
        pixels[1] = (0, 0, 0)
        pixels[2] = (0, 0, 0)
    elif diff == 0:
        pixels[0] = (255, 255, 0)
        pixels[1] = (0, 0, 0)
        pixels[2] = (0, 0, 0)
    elif diff >= -3:
        pixels[0] = (255, 0, 0)
        pixels[1] = (0, 0, 0)
        pixels[2] = (0, 0, 0)
    elif diff >= -6:
        pixels[0] = (255, 0, 0)
        pixels[1] = (255, 0, 0)
        pixels[2] = (0, 0, 0)
    else:
        pixels[0] = (255, 0, 0)
        pixels[1] = (255, 0, 0)
        pixels[2] = (255, 0, 0)

def clear_health_bar():
    for i in range(NUM_LEDS):
        pixels[i] = (0, 0, 0)

def flash_leds_gradient():
    """Flash LEDs with color gradient for multiplayer hit"""
    # Gradient sequence: green -> cyan -> blue -> purple
    gradient = [
        (0, 255, 0),      # Green
        (0, 255, 128),    # Green-cyan
        (0, 255, 255),    # Cyan
        (0, 128, 255),    # Cyan-blue
        (0, 0, 255),      # Blue
        (128, 0, 255),    # Blue-purple
        (255, 0, 255),    # Purple
    ]
    
    for color in gradient:
        for i in range(NUM_LEDS):
            pixels[i] = color
        time.sleep(0.04)
    
    # Return to score display
    update_mp_health_bar()

def flash_leds_red():
    """Flash LEDs red for multiplayer miss"""
    for _ in range(3):
        for i in range(NUM_LEDS):
            pixels[i] = (255, 0, 0)
        time.sleep(0.08)
        for i in range(NUM_LEDS):
            pixels[i] = (0, 0, 0)
        time.sleep(0.08)
    
    # Return to score display
    update_mp_health_bar()

# Claw labels
start_x = (SCREEN_WIDTH - CLAW_WIDTH) // 2

claw_line1 = label.Label(terminalio.FONT, text="   ||", color=0xFFFFFF, x=start_x, y=CLAW_Y1_BASE)
claw_line2 = label.Label(terminalio.FONT, text="  ====", color=0xFFFFFF, x=start_x, y=CLAW_Y2_BASE)
claw_line3 = label.Label(terminalio.FONT, text="  |  |", color=0xFFFFFF, x=start_x, y=CLAW_Y3_BASE)

splash.append(claw_line1)
splash.append(claw_line2)
splash.append(claw_line3)

claw_line1.hidden = True
claw_line2.hidden = True
claw_line3.hidden = True

def set_claw_y(offset):
    claw_line1.y = CLAW_Y1_BASE + offset
    claw_line2.y = CLAW_Y2_BASE + offset
    claw_line3.y = CLAW_Y3_BASE + offset

# Single-player ball
ball_x = random.randint(BALL_WIDTH, SCREEN_WIDTH - BALL_WIDTH)
ball_label = label.Label(terminalio.FONT, text="*", color=0xFFFFFF, x=ball_x, y=BALL_Y)
splash.append(ball_label)

# Player dot (for multiplayer)
player_label = label.Label(terminalio.FONT, text="*", color=0xFFFFFF, x=player_x, y=PLAYER_Y)
splash.append(player_label)
player_label.hidden = True

# Single-player ball functions
def reset_ball():
    global ball_x
    ball_x = random.randint(BALL_WIDTH, SCREEN_WIDTH - BALL_WIDTH)
    ball_label.x = ball_x

def check_hit_easy():
    claw_left = claw_line1.x
    claw_right = claw_left + CLAW_WIDTH
    ball_center = ball_x + BALL_WIDTH // 4
    return (ball_center >= claw_left) and (ball_center <= claw_right)

# MEDIUM mode functions
def clear_medium_balls():
    global medium_balls
    for b in medium_balls:
        if b["label"] in splash:
            splash.remove(b["label"])
    medium_balls = []

def spawn_medium_ball():
    global medium_balls
    if len(medium_balls) >= MEDIUM_MAX_BALLS:
        return
    x = random.randint(0, SCREEN_WIDTH - BALL_WIDTH)
    life = random.uniform(MEDIUM_BALL_MIN_LIFE, MEDIUM_BALL_MAX_LIFE)
    expire = time.monotonic() + life
    lbl = label.Label(terminalio.FONT, text="*", color=0xFFFFFF, x=x, y=BALL_Y)
    splash.append(lbl)
    medium_balls.append({"label": lbl, "x": x, "expire": expire})

def update_medium_balls():
    global medium_balls
    now = time.monotonic()
    still_alive = []
    for b in medium_balls:
        if now > b["expire"]:
            if b["label"] in splash:
                splash.remove(b["label"])
        else:
            still_alive.append(b)
    medium_balls = still_alive
    if len(medium_balls) < MEDIUM_MAX_BALLS:
        if random.random() < 0.08:
            spawn_medium_ball()

def check_hit_medium():
    global medium_balls
    claw_left = claw_line1.x
    claw_right = claw_left + CLAW_WIDTH
    for i, b in enumerate(medium_balls):
        ball_center = b["x"] + BALL_WIDTH // 2
        if (ball_center >= claw_left) and (ball_center <= claw_right):
            if b["label"] in splash:
                splash.remove(b["label"])
            del medium_balls[i]
            return True
    return False

# HARD mode functions
def clear_hard_balls():
    global hard_balls
    for b in hard_balls:
        if b["label"] in splash:
            splash.remove(b["label"])
    hard_balls = []

def hard_speed_for_level():
    return HARD_BASE_SPEED + HARD_SPEED_STEP * current_level_index

def hard_num_balls_for_level():
    level = current_level_index + 1
    if level <= 7:
        return 1
    elif level <= 9:
        return 2
    else:
        return 3

def spawn_hard_ball(speed):
    global hard_balls
    x = random.randint(0, SCREEN_WIDTH - BALL_WIDTH)
    direction = 1 if random.random() < 0.5 else -1
    vx = speed * direction
    lbl = label.Label(terminalio.FONT, text="*", color=0xFFFFFF, x=int(x), y=BALL_Y)
    splash.append(lbl)
    hard_balls.append({"label": lbl, "x": float(x), "vx": float(vx)})

def init_hard_balls_for_level():
    clear_hard_balls()
    speed = hard_speed_for_level()
    num = hard_num_balls_for_level()
    for _ in range(num):
        spawn_hard_ball(speed)

def update_hard_balls():
    max_x = SCREEN_WIDTH - BALL_WIDTH
    for b in hard_balls:
        x = b["x"] + b["vx"]
        if x < 0:
            x = 0
            b["vx"] = abs(b["vx"])
        elif x > max_x:
            x = max_x
            b["vx"] = -abs(b["vx"])
        b["x"] = x
        b["label"].x = int(x)

def check_hit_hard():
    global hard_balls
    claw_left = claw_line1.x
    claw_right = claw_left + CLAW_WIDTH
    for i, b in enumerate(hard_balls):
        ball_center = b["x"] + BALL_WIDTH / 2
        if (ball_center >= claw_left) and (ball_center <= claw_right):
            if b["label"] in splash:
                splash.remove(b["label"])
            del hard_balls[i]
            speed = hard_speed_for_level()
            spawn_hard_ball(speed)
            return True
    return False

# Mode starters
def start_easy():
    global game_mode, current_level_index, time_limit, target_hits
    global hits_remaining, round_start_time, game_state
    
    game_mode = "EASY"
    clear_health_bar()
    current_level_index = 0
    time_limit, target_hits = LEVEL_DATA[current_level_index]
    hits_remaining = target_hits
    round_start_time = time.monotonic()
    game_state = "PLAYING"
    
    title_label.text = "EASY"
    level_label.text = f"Lv{current_level_index + 1}"
    timer_label.text = f"{time_limit:4.1f}"
    hits_label.text = str(hits_remaining)
    message_label.text = ""
    
    ball_label.hidden = False
    player_label.hidden = True
    reset_ball()
    clear_medium_balls()
    clear_hard_balls()
    
    claw_line1.hidden = False
    claw_line2.hidden = False
    claw_line3.hidden = False

def start_medium():
    global game_mode, current_level_index, time_limit, target_hits
    global hits_remaining, round_start_time, game_state, lives
    
    game_mode = "MEDIUM"
    current_level_index = 0
    time_limit, target_hits = LEVEL_DATA[current_level_index]
    hits_remaining = target_hits
    round_start_time = time.monotonic()
    game_state = "PLAYING"
    lives = 3
    update_health_bar()
    
    title_label.text = "MEDIUM"
    level_label.text = f"Lv{current_level_index + 1}"
    timer_label.text = f"{time_limit:4.1f}"
    hits_label.text = str(hits_remaining)
    message_label.text = ""
    
    ball_label.hidden = True
    player_label.hidden = True
    clear_medium_balls()
    clear_hard_balls()
    for _ in range(random.randint(1, MEDIUM_MAX_BALLS)):
        spawn_medium_ball()
    
    claw_line1.hidden = False
    claw_line2.hidden = False
    claw_line3.hidden = False

def start_hard():
    global game_mode, current_level_index, time_limit, target_hits
    global hits_remaining, round_start_time, game_state, lives
    
    game_mode = "HARD"
    current_level_index = 0
    time_limit, target_hits = LEVEL_DATA[current_level_index]
    hits_remaining = target_hits
    round_start_time = time.monotonic()
    game_state = "PLAYING"
    lives = 3
    update_health_bar()
    
    title_label.text = "HARD"
    level_label.text = f"Lv{current_level_index + 1}"
    timer_label.text = f"{time_limit:4.1f}"
    hits_label.text = str(hits_remaining)
    message_label.text = ""
    
    ball_label.hidden = True
    player_label.hidden = True
    clear_medium_balls()
    init_hard_balls_for_level()
    
    claw_line1.hidden = False
    claw_line2.hidden = False
    claw_line3.hidden = False

def start_multiplayer():
    global game_mode, game_state, mp_round_start, mp_score_shooter, mp_score_dodger
    
    game_mode = "MULTIPLAYER"
    game_state = "PLAYING"
    mp_score_shooter = 0
    mp_score_dodger = 0
    mp_round_start = time.monotonic()
    update_mp_health_bar()
    
    title_label.text = "SHOOTER"
    level_label.text = f"You:{mp_score_shooter}"
    timer_label.text = f"{MP_ROUND_TIME:.0f}"
    hits_label.text = f"Opp:{mp_score_dodger}"
    message_label.text = ""
    
    ball_label.hidden = True
    player_label.hidden = False
    player_label.x = SCREEN_WIDTH // 2
    clear_medium_balls()
    clear_hard_balls()
    
    claw_line1.hidden = False
    claw_line2.hidden = False
    claw_line3.hidden = False

def start_level_same_difficulty():
    global time_limit, target_hits, hits_remaining, round_start_time, game_state, lives
    
    time_limit, target_hits = LEVEL_DATA[current_level_index]
    hits_remaining = target_hits
    round_start_time = time.monotonic()
    game_state = "PLAYING"
    
    level_label.text = f"Lv{current_level_index + 1}"
    timer_label.text = f"{time_limit:4.1f}"
    hits_label.text = str(hits_remaining)
    message_label.text = ""
    
    if game_mode in ("MEDIUM", "HARD"):
        lives = 3
        update_health_bar()
    else:
        clear_health_bar()
    
    if game_mode == "EASY":
        ball_label.hidden = False
        reset_ball()
        clear_medium_balls()
        clear_hard_balls()
    elif game_mode == "MEDIUM":
        ball_label.hidden = True
        clear_medium_balls()
        clear_hard_balls()
        for _ in range(random.randint(1, MEDIUM_MAX_BALLS)):
            spawn_medium_ball()
    elif game_mode == "HARD":
        ball_label.hidden = True
        clear_medium_balls()
        init_hard_balls_for_level()

# Menu functions
def show_menu():
    global in_menu
    
    in_menu = True
    clear_health_bar()
    
    claw_line1.hidden = True
    claw_line2.hidden = True
    claw_line3.hidden = True
    
    ball_label.hidden = True
    player_label.hidden = True
    clear_medium_balls()
    clear_hard_balls()
    
    title_label.text = "MENU"
    level_label.text = ""
    timer_label.text = ""
    hits_label.text = ""
    
    current_option = MENU_OPTIONS[menu_index]
    message_label.text = f"< {current_option} >"

# Drop claw animation
def drop_claw():
    global hits_remaining, game_state, current_level_index, lives
    
    if game_state != "PLAYING":
        return
    
    # Drop animation
    for step in range(DROP_STEPS + 1):
        offset = step * DROP_STEP_PIXELS
        set_claw_y(offset)
        if game_mode == "MEDIUM":
            update_medium_balls()
        elif game_mode == "HARD":
            update_hard_balls()
        time.sleep(0.03)
    
    # Check hit
    if game_mode == "EASY":
        hit = check_hit_easy()
    elif game_mode == "MEDIUM":
        hit = check_hit_medium()
    else:
        hit = check_hit_hard()
    
    if hit:
        sfx_hit()
        if game_mode == "EASY":
            reset_ball()
        hits_remaining -= 1
        if hits_remaining < 0:
            hits_remaining = 0
        hits_label.text = str(hits_remaining)
        
        if hits_remaining == 0:
            if current_level_index < len(LEVEL_DATA) - 1:
                current_level_index += 1
                start_level_same_difficulty()
                sfx_level_up()
            else:
                game_state = "WIN"
                message_label.text = "YOU WIN!"
    else:
        sfx_miss()
        if game_mode in ("MEDIUM", "HARD"):
            lives -= 1
            if lives < 0:
                lives = 0
            update_health_bar()
            if lives == 0:
                game_state = "GAME_OVER"
                message_label.text = "GAME OVER"
                sfx_game_over()
    
    time.sleep(0.15)
    
    # Raise claw
    for step in range(DROP_STEPS, -1, -1):
        offset = step * DROP_STEP_PIXELS
        set_claw_y(offset)
        if game_mode == "MEDIUM":
            update_medium_balls()
        elif game_mode == "HARD":
            update_hard_balls()
        time.sleep(0.03)

# Multiplayer UART functions
def process_uart():
    """Receive player position from dodger"""
    global player_x
    latest_x = None
    while True:
        try:
            data = uart.readline()
        except Exception:
            break
        if not data:
            break
        try:
            msg = data.decode().strip()
        except Exception:
            continue
        
        if msg.startswith("P:"):
            try:
                val_str = msg.split(":", 1)[1]
                val = int(val_str)
                latest_x = val
            except Exception:
                pass
    
    if latest_x is not None:
        player_x = latest_x
        player_label.x = player_x

def send_fire():
    """Send fire command to dodger"""
    try:
        uart.write("FIRE:1\n".encode())
    except Exception:
        pass

def send_aim_position(accel_val):
    """Send aim position to dodger"""
    global last_aim_sent
    now = time.monotonic()
    if now - last_aim_sent < AIM_SEND_INTERVAL:
        return
    try:
        msg = f"AIM:{accel_val:.1f}\n"
        uart.write(msg.encode())
        last_aim_sent = now
    except Exception:
        pass

def drop_claw_mp():
    """Multiplayer claw drop with hit detection"""
    global mp_score_shooter, mp_score_dodger, claw_dropping, game_state
    
    # Drop animation
    for step in range(DROP_STEPS + 1):
        offset = step * DROP_STEP_PIXELS
        set_claw_y(offset)
        time.sleep(0.03)
    
    # Check if hit
    claw_left = claw_line1.x
    claw_right = claw_left + CLAW_WIDTH
    player_center = player_x + PLAYER_WIDTH // 2
    
    if (player_center >= claw_left) and (player_center <= claw_right):
        # HIT!
        mp_score_shooter += MP_HIT_POINTS
        sfx_mp_hit()
        flash_leds_gradient()
    else:
        # MISS!
        mp_score_dodger += MP_MISS_POINTS
        sfx_mp_miss()
        flash_leds_red()
    
    level_label.text = f"You:{mp_score_shooter}"
    hits_label.text = f"Opp:{mp_score_dodger}"
    
    time.sleep(0.15)
    
    # Raise claw
    for step in range(DROP_STEPS, -1, -1):
        offset = step * DROP_STEP_PIXELS
        set_claw_y(offset)
        time.sleep(0.03)

# Initialize
show_menu()

# Main loop
while True:
    # Button handling
    current_btn = rot_btn.value
    button_pressed = last_btn_state and (not current_btn)
    last_btn_state = current_btn
    
    # Rotary encoder (for menu navigation)
    current_rot_a = rot_a.value
    if in_menu and (current_rot_a != rot_last_state):
        if not current_rot_a:
            if rot_b.value:
                menu_index += 1
            else:
                menu_index -= 1
            
            # Wrap around
            if menu_index < 0:
                menu_index = len(MENU_OPTIONS) - 1
            if menu_index >= len(MENU_OPTIONS):
                menu_index = 0
            
            current_option = MENU_OPTIONS[menu_index]
            message_label.text = f"< {current_option} >"
        
        rot_last_state = current_rot_a
    
    # ========== MENU LOGIC ==========
    if in_menu:
        if button_pressed:
            selected = MENU_OPTIONS[menu_index]
            
            if selected == "EASY":
                in_menu = False
                start_easy()
            elif selected == "MEDIUM":
                in_menu = False
                start_medium()
            elif selected == "HARD":
                in_menu = False
                start_hard()
            elif selected == "MULTIPLAYER":
                if uart_available:
                    in_menu = False
                    start_multiplayer()
                else:
                    message_label.text = "UART N/A"
        
        time.sleep(0.02)
        continue
    
    # ========== SINGLE-PLAYER GAME LOGIC ==========
    if game_mode in ("EASY", "MEDIUM", "HARD"):
        now = time.monotonic()
        elapsed = now - round_start_time
        remaining = time_limit - elapsed
        if remaining < 0:
            remaining = 0.0
        
        timer_label.text = f"{remaining:4.1f}"
        
        if game_state == "PLAYING" and remaining <= 0 and hits_remaining > 0:
            game_state = "GAME_OVER"
            message_label.text = "GAME OVER"
            sfx_game_over()
        
        if game_state == "PLAYING":
            if game_mode == "MEDIUM":
                update_medium_balls()
            elif game_mode == "HARD":
                update_hard_balls()
        
        # Read accelerometer
        raw_x, raw_y, raw_z = accelerometer.acceleration
        centered_x = raw_x - offset_x
        filtered_x = ACCEL_ALPHA * centered_x + (1.0 - ACCEL_ALPHA) * filtered_x
        
        claw_x = int(map_range(filtered_x, ACCEL_MIN, ACCEL_MAX, 0, SCREEN_WIDTH - CLAW_WIDTH))
        claw_line1.x = claw_x
        claw_line2.x = claw_x
        claw_line3.x = claw_x
        
        if button_pressed:
            if game_state == "PLAYING" and remaining > 0:
                drop_claw()
            elif game_state in ("GAME_OVER", "WIN"):
                show_menu()
    
    # ========== MULTIPLAYER GAME LOGIC ==========
    elif game_mode == "MULTIPLAYER":
        # Check timer
        now = time.monotonic()
        elapsed = now - mp_round_start
        remaining = MP_ROUND_TIME - elapsed
        if remaining < 0:
            remaining = 0.0
        
        timer_label.text = f"{remaining:.0f}s"
        
        # Check if time's up
        if game_state == "PLAYING" and remaining <= 0:
            game_state = "GAME_OVER"
            if mp_score_shooter > mp_score_dodger:
                message_label.text = "YOU WIN!"
                sfx_level_up()
            elif mp_score_shooter < mp_score_dodger:
                message_label.text = "YOU LOSE!"
                sfx_game_over()
            else:
                message_label.text = "TIE!"
            # Reset button state to allow clean restart
            last_btn_state = rot_btn.value
        
        # Process incoming player position
        process_uart()
        
        # Read accelerometer for aiming
        try:
            raw_x, raw_y, raw_z = accelerometer.acceleration
        except Exception:
            raw_x = 0.0
        
        # Update local claw position
        claw_x = int(map_range(raw_x, ACCEL_MIN, ACCEL_MAX, 0, SCREEN_WIDTH - CLAW_WIDTH))
        if not claw_dropping:
            claw_line1.x = claw_x
            claw_line2.x = claw_x
            claw_line3.x = claw_x
        
        # Send aim position to dodger
        if game_state == "PLAYING":
            send_aim_position(raw_x)
        
        # Fire button
        if button_pressed:
            if game_state == "PLAYING" and not claw_dropping:
                send_fire()
                claw_dropping = True
                drop_claw_mp()
                claw_dropping = False
            elif game_state == "GAME_OVER":
                show_menu()
    
    time.sleep(0.015)

