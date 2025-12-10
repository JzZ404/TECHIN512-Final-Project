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

CLAW_WIDTH = 40   # 文本爪子的宽度（大概估计即可）

# 爪子三行的基础 Y（行间距看这里）
CLAW_Y1_BASE = 14
CLAW_Y2_BASE = 24
CLAW_Y3_BASE = 36

# 爪子下落动画
DROP_STEPS = 10          # 分成多少步掉下去
DROP_STEP_PIXELS = 3     # 每一步掉多少像素

ACCEL_MIN = -4.0
ACCEL_MAX = 4.0

# --- Accelerometer calibration + filtering settings ---
ACCEL_CALIB_SAMPLES = 200   # how many samples to average at startup
ACCEL_ALPHA = 0.2           # EMA smoothing factor (0–1, higher = more responsive)

# will be set during calibration
offset_x = 0.0
filtered_x = 0.0

BALL_WIDTH = 18
BALL_Y = 60              # 小球的高度（越大越靠下）

# MEDIUM 模式：多球设置（打地鼠）
MEDIUM_MAX_BALLS = 3
MEDIUM_BALL_MIN_LIFE = 1.0   # 每个球出现时间下限（秒）
MEDIUM_BALL_MAX_LIFE = 3.0   # 上限

# HARD 模式：移动球速度
HARD_BASE_SPEED = 0.7        # 每帧像素速度（Level 1）
HARD_SPEED_STEP = 0.25       # 每升一级增加速度

# 旋钮按钮引脚
ROT_BTN_PIN = board.D0

# Rotary 编码器 A/B
ROT_A_PIN = board.D8
ROT_B_PIN = board.D9

# NeoPixel 设置（3 颗命灯）
LED_PIN = board.D1
NUM_LEDS = 3

# --------------------
# BUZZER on D3
# --------------------

buzzer = pwmio.PWMOut(
    board.D3,
    frequency=2000,
    duty_cycle=0,
    variable_frequency=True  # <-- THIS IS THE IMPORTANT PART
)


def beep(freq=2000, duration=0.08):
    """Simple short beep."""
    buzzer.frequency = freq
    buzzer.duty_cycle = 32768  # 50% volume
    time.sleep(duration)
    buzzer.duty_cycle = 0

# 难度菜单
DIFFICULTY_OPTIONS = ["EASY", "MEDIUM", "HARD"]

# 10 关的时间与目标命中数（3 个难度共用）
LEVEL_DATA = [
    # (time_limit_sec, target_hits)
    (30.0, 3),   # Level 1
    (30.0, 4),   # Level 2
    (30.0, 5),   # Level 3
    (25.0, 5),   # Level 4
    (25.0, 6),   # Level 5
    (20.0, 6),   # Level 6
    (20.0, 7),   # Level 7
    (15.0, 7),   # Level 8
    (15.0, 8),   # Level 9
    (12.0, 8),   # Level 10
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


def map_range(x, in_min, in_max, out_min, out_max):
    # 简单线性映射 + clamp
    if x < in_min:
        x = in_min
    if x > in_max:
        x = in_max
    return out_min + (out_max - out_min) * (x - in_min) / (in_max - in_min)


# 硬件初始化
displayio.release_displays()

i2c = busio.I2C(board.SCL, board.SDA)

# SSD1306 OLED
display_bus = i2cdisplaybus.I2CDisplayBus(i2c, device_address=0x3C)
display = adafruit_displayio_ssd1306.SSD1306(
    display_bus, width=SCREEN_WIDTH, height=SCREEN_HEIGHT
)

# ADXL345 加速度计
accelerometer = adafruit_adxl34x.ADXL345(i2c)
accelerometer.range = adafruit_adxl34x.Range.RANGE_2_G

# --- Calibrate accelerometer X offset (assume device is held level) ---
print("Calibrating accelerometer... please keep the device still")
offset_sum = 0.0
for i in range(ACCEL_CALIB_SAMPLES):
    x, y, z = accelerometer.acceleration
    offset_sum += x
    time.sleep(0.01)  # small delay between samples

offset_x = offset_sum / ACCEL_CALIB_SAMPLES
filtered_x = 0.0
print("Calibration done, offset_x =", offset_x)

# 旋钮按钮（active LOW）
rot_btn = digitalio.DigitalInOut(ROT_BTN_PIN)
rot_btn.switch_to_input(pull=digitalio.Pull.UP)
last_btn_state = rot_btn.value

# Rotary A/B（菜单用来旋转选择）
rot_a = digitalio.DigitalInOut(ROT_A_PIN)
rot_a.switch_to_input(pull=digitalio.Pull.UP)
rot_b = digitalio.DigitalInOut(ROT_B_PIN)
rot_b.switch_to_input(pull=digitalio.Pull.UP)
rot_last_state = rot_a.value

# NeoPixel（3 条命）
pixels = neopixel.NeoPixel(
    LED_PIN,
    NUM_LEDS,
    brightness=0.3,
    auto_write=True
)

# 根 Group
splash = displayio.Group()
display.root_group = splash

# --------------------
# 游戏 / 菜单 状态变量
# --------------------
in_menu = True                # 开机先进菜单
menu_index = 0                # 当前选中的难度
difficulty = None             # "EASY" / "MEDIUM" / "HARD"

current_level_index = 0       # 0 表示 Level 1
time_limit = 0.0
target_hits = 0
hits_remaining = 0
round_start_time = 0.0
game_state = "PLAYING"        # PLAYING / GAME_OVER / WIN

lives = 3                     # MEDIUM/HARD 用

# MEDIUM 的多球列表：每个元素是 dict: {"label":..., "x":..., "expire":...}
medium_balls = []

# HARD 的移动球列表：每个元素是 dict: {"label":..., "x":..., "vx":...}
hard_balls = []

# --------------------
# UI：标题、Lv、倒计时、目标剩余数、居中提示
# --------------------
# 顶部中间：菜单标题 / 难度标题
title_label = label.Label(
    terminalio.FONT,
    text="",
    color=0xFFFFFF,
)
title_label.anchor_point = (0.5, 0.0)  # 顶部中间
title_label.anchored_position = (SCREEN_WIDTH // 2, 0)
splash.append(title_label)

# 左上第一行：Level 显示（Lv1）
level_label = label.Label(
    terminalio.FONT,
    text="",
    color=0xFFFFFF,
)
level_label.anchor_point = (0.0, 0.0)  # 左上
level_label.anchored_position = (0, 0)
splash.append(level_label)

# 左上第二行：倒计时
timer_label = label.Label(
    terminalio.FONT,
    text="",
    color=0xFFFFFF,
)
timer_label.anchor_point = (0.0, 0.0)  # 左上（第二行）
timer_label.anchored_position = (0, 10)
splash.append(timer_label)

# 顶右：还需要命中的次数（hits remaining）
hits_label = label.Label(
    terminalio.FONT,
    text="",
    color=0xFFFFFF,
)
hits_label.anchor_point = (1.0, 0.0)   # 右上角
hits_label.anchored_position = (SCREEN_WIDTH - 2, 0)
splash.append(hits_label)

# 中间消息（菜单难度文本 / Game Over / You Win）
message_label = label.Label(
    terminalio.FONT,
    text="",
    color=0xFFFFFF,
)
message_label.anchor_point = (0.5, 0.5)
message_label.anchored_position = (SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2)
splash.append(message_label)

# --------------------
# 生命显示（NeoPixel）
# --------------------
def update_health_bar():
    """
    3 颗灯显示 3 条命：
    - 绿：还活着
    - 红：用掉
    Medium / Hard 模式用，Easy 模式直接关灯。
    """
    for i in range(NUM_LEDS):
        if i < lives:
            pixels[i] = (0, 255, 0)   # 剩余命 = 绿
        else:
            pixels[i] = (255, 0, 0)   # 用掉的命 = 红


def clear_health_bar():
    """Easy 模式 or 菜单：全灭。"""
    for i in range(NUM_LEDS):
        pixels[i] = (0, 0, 0)

# --------------------
# 爪子 (3 行 ASCII)
# --------------------
start_x = (SCREEN_WIDTH - CLAW_WIDTH) // 2

claw_line1 = label.Label(
    terminalio.FONT,
    text="   ||",
    color=0xFFFFFF,
    x=start_x,
    y=CLAW_Y1_BASE,
)

claw_line2 = label.Label(
    terminalio.FONT,
    text="  ====",
    color=0xFFFFFF,
    x=start_x,
    y=CLAW_Y2_BASE,
)

claw_line3 = label.Label(
    terminalio.FONT,
    text="  |  |",
    color=0xFFFFFF,
    x=start_x,
    y=CLAW_Y3_BASE,
)

splash.append(claw_line1)
splash.append(claw_line2)
splash.append(claw_line3)

# 一开始在菜单里，不要显示爪子
claw_line1.hidden = True
claw_line2.hidden = True
claw_line3.hidden = True


def set_claw_y(offset):
    """垂直位移爪子（offset 为相对偏移量）"""
    claw_line1.y = CLAW_Y1_BASE + offset
    claw_line2.y = CLAW_Y2_BASE + offset
    claw_line3.y = CLAW_Y3_BASE + offset


# --------------------
# EASY 模式用的单个小球
# --------------------
ball_x = random.randint(BALL_WIDTH, SCREEN_WIDTH - BALL_WIDTH)

ball_label = label.Label(
    terminalio.FONT,
    text="*",
    color=0xFFFFFF,
    x=ball_x,
    y=BALL_Y,
)

splash.append(ball_label)


def reset_ball():
    """EASY 模式下，重新随机一个固定的球。"""
    global ball_x
    ball_x = random.randint(BALL_WIDTH, SCREEN_WIDTH - BALL_WIDTH)
    ball_label.x = ball_x


def check_hit_easy():
    """Easy 模式：判断固定星星是否在爪子下方（只看水平范围）"""
    claw_left = claw_line1.x
    claw_right = claw_left + CLAW_WIDTH
    ball_center = ball_x + BALL_WIDTH // 4
    return (ball_center >= claw_left) and (ball_center <= claw_right)


# --------------------
# MEDIUM 模式多球相关函数（打地鼠）
# --------------------
def clear_medium_balls():
    """删除 MEDIUM 模式所有小球。"""
    global medium_balls
    for b in medium_balls:
        if b["label"] in splash:
            splash.remove(b["label"])
    medium_balls = []


def spawn_medium_ball():
    """在 MEDIUM 中随机生成一个新球（如果没满）。"""
    global medium_balls
    if len(medium_balls) >= MEDIUM_MAX_BALLS:
        return

    x = random.randint(0, SCREEN_WIDTH - BALL_WIDTH)
    life = random.uniform(MEDIUM_BALL_MIN_LIFE, MEDIUM_BALL_MAX_LIFE)
    expire = time.monotonic() + life

    lbl = label.Label(
        terminalio.FONT,
        text="*",
        color=0xFFFFFF,
        x=x,
        y=BALL_Y,
    )
    splash.append(lbl)

    medium_balls.append({
        "label": lbl,
        "x": x,
        "expire": expire,
    })


def update_medium_balls():
    """更新 MEDIUM 模式的球：处理消失 + 随机新生成。"""
    global medium_balls

    now = time.monotonic()

    # 先移除过期的
    still_alive = []
    for b in medium_balls:
        if now > b["expire"]:
            # 过期，移除
            if b["label"] in splash:
                splash.remove(b["label"])
        else:
            still_alive.append(b)
    medium_balls = still_alive

    # 再看是否可以生成新球（最多 MEDIUM_MAX_BALLS 个）
    if len(medium_balls) < MEDIUM_MAX_BALLS:
        # 用一个小概率来生成，避免刷屏
        if random.random() < 0.08:
            spawn_medium_ball()


def check_hit_medium():
    """
    Medium 模式：检查当前爪子是否打中任意一个球。
    命中一个就返回 True，并把该球移除（像 whack-a-mole 一样）。
    """
    global medium_balls

    claw_left = claw_line1.x
    claw_right = claw_left + CLAW_WIDTH

    for i, b in enumerate(medium_balls):
        ball_center = b["x"] + BALL_WIDTH // 2
        if (ball_center >= claw_left) and (ball_center <= claw_right):
            # 命中：移除该球
            if b["label"] in splash:
                splash.remove(b["label"])
            del medium_balls[i]
            return True

    return False


# --------------------
# HARD 模式移动球相关
# --------------------
def clear_hard_balls():
    """删除 HARD 模式所有小球。"""
    global hard_balls
    for b in hard_balls:
        if b["label"] in splash:
            splash.remove(b["label"])
    hard_balls = []


def hard_speed_for_level():
    """根据当前 Level 返回此关卡球的速度（像素/帧）。"""
    return HARD_BASE_SPEED + HARD_SPEED_STEP * current_level_index


def hard_num_balls_for_level():
    """根据关卡决定 HARD 模式同时存在的小球数。"""
    level = current_level_index + 1  # 1~10
    if level <= 7:
        return 1
    elif level <= 9:
        return 2
    else:
        return 3


def spawn_hard_ball(speed):
    """在 HARD 中生成一个会左右移动的小球。"""
    global hard_balls

    x = random.randint(0, SCREEN_WIDTH - BALL_WIDTH)
    # 随机方向
    direction = 1 if random.random() < 0.5 else -1
    vx = speed * direction

    lbl = label.Label(
        terminalio.FONT,
        text="*",
        color=0xFFFFFF,
        x=int(x),
        y=BALL_Y,
    )
    splash.append(lbl)

    hard_balls.append({
        "label": lbl,
        "x": float(x),
        "vx": float(vx),
    })


def init_hard_balls_for_level():
    """根据当前关卡，初始化对应数量 + 速度的 HARD 球。"""
    clear_hard_balls()
    speed = hard_speed_for_level()
    num = hard_num_balls_for_level()
    for _ in range(num):
        spawn_hard_ball(speed)


def update_hard_balls():
    """每帧更新 HARD 模式小球的移动（左右弹跳）。"""
    max_x = SCREEN_WIDTH - BALL_WIDTH
    for b in hard_balls:
        x = b["x"] + b["vx"]
        # 碰到左右边界，反弹
        if x < 0:
            x = 0
            b["vx"] = abs(b["vx"])
        elif x > max_x:
            x = max_x
            b["vx"] = -abs(b["vx"])
        b["x"] = x
        b["label"].x = int(x)


def check_hit_hard():
    """
    HARD 模式：检查爪子是否打中任意一个移动球。
    命中一个就返回 True，并把该球移除 + 立刻生成一个新的移动球
    （保证场上球数量不变）。
    """
    global hard_balls

    claw_left = claw_line1.x
    claw_right = claw_left + CLAW_WIDTH

    for i, b in enumerate(hard_balls):
        ball_center = b["x"] + BALL_WIDTH / 2
        if (ball_center >= claw_left) and (ball_center <= claw_right):
            # 命中：移除该球
            if b["label"] in splash:
                splash.remove(b["label"])
            del hard_balls[i]

            # 立刻生成一个新的，以保持数量
            speed = hard_speed_for_level()
            spawn_hard_ball(speed)
            return True

    return False


# --------------------
# 初始化不同难度的关卡
# --------------------
def start_easy():
    """Easy：有计时、无生命、LED 灭、单一固定球。"""
    global difficulty, current_level_index, time_limit, target_hits
    global hits_remaining, round_start_time, game_state

    difficulty = "EASY"
    clear_health_bar()

    current_level_index = 0  # Level 1
    time_limit, target_hits = LEVEL_DATA[current_level_index]
    hits_remaining = target_hits
    round_start_time = time.monotonic()
    game_state = "PLAYING"

    title_label.text = "EASY"
    level_label.text = f"Lv{current_level_index + 1}"
    timer_label.text = f"{time_limit:4.1f}"
    hits_label.text = str(hits_remaining)
    message_label.text = ""

    # EASY 用单球
    ball_label.hidden = False
    reset_ball()

    # 清掉 MEDIUM / HARD 的球
    clear_medium_balls()
    clear_hard_balls()

    # 显示爪子
    claw_line1.hidden = False
    claw_line2.hidden = False
    claw_line3.hidden = False


def start_medium():
    """Medium：有计时 + 3 条命 + LED 血条 + 多个随机球打地鼠。"""
    global difficulty, current_level_index, time_limit, target_hits
    global hits_remaining, round_start_time, game_state, lives

    difficulty = "MEDIUM"
    current_level_index = 0  # Level 1
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

    # 隐藏 EASY 的单球
    ball_label.hidden = True

    # 初始化 MEDIUM 多球
    clear_medium_balls()
    clear_hard_balls()
    for _ in range(random.randint(1, MEDIUM_MAX_BALLS)):
        spawn_medium_ball()

    # 显示爪子
    claw_line1.hidden = False
    claw_line2.hidden = False
    claw_line3.hidden = False


def start_hard():
    """Hard：有计时 + 3 条命 + LED 血条 + 移动小球，后 3 关多球。"""
    global difficulty, current_level_index, time_limit, target_hits
    global hits_remaining, round_start_time, game_state, lives

    difficulty = "HARD"
    current_level_index = 0  # Level 1
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

    # 隐藏 EASY 的单球 & MEDIUM 多球
    ball_label.hidden = True
    clear_medium_balls()

    # 初始化 HARD 移动球
    init_hard_balls_for_level()

    # 显示爪子
    claw_line1.hidden = False
    claw_line2.hidden = False
    claw_line3.hidden = False


def start_level_same_difficulty():
    """在同一个 difficulty 下切换下一关（重置 time & target & 命/球）。"""
    global time_limit, target_hits, hits_remaining, round_start_time, game_state, lives

    time_limit, target_hits = LEVEL_DATA[current_level_index]
    hits_remaining = target_hits
    round_start_time = time.monotonic()
    game_state = "PLAYING"

    level_label.text = f"Lv{current_level_index + 1}"
    timer_label.text = f"{time_limit:4.1f}"
    hits_label.text = str(hits_remaining)
    message_label.text = ""

    if difficulty in ("MEDIUM", "HARD"):
        lives = 3
        update_health_bar()
    else:
        clear_health_bar()

    if difficulty == "EASY":
        ball_label.hidden = False
        reset_ball()
        clear_medium_balls()
        clear_hard_balls()
    elif difficulty == "MEDIUM":
        ball_label.hidden = True
        clear_medium_balls()
        clear_hard_balls()
        for _ in range(random.randint(1, MEDIUM_MAX_BALLS)):
            spawn_medium_ball()
    elif difficulty == "HARD":
        ball_label.hidden = True
        clear_medium_balls()
        init_hard_balls_for_level()


# --------------------
# 菜单显示
# --------------------
def show_menu():
    global in_menu

    in_menu = True
    clear_health_bar()

    # 隐藏爪子（菜单不显示）
    claw_line1.hidden = True
    claw_line2.hidden = True
    claw_line3.hidden = True

    # 隐藏所有球
    ball_label.hidden = True
    clear_medium_balls()
    clear_hard_balls()

    # 顶部中间显示 MENU
    title_label.text = "MENU"

    # 左上内容清空
    level_label.text = ""
    timer_label.text = ""
    hits_label.text = ""

    # 中间一行：< EASY > / < MEDIUM > / < HARD >
    current_name = DIFFICULTY_OPTIONS[menu_index]
    message_label.text = f"< {current_name} >"


# --------------------
# 爪子下落动画（修正版：MEDIUM/HARD 球在动画中仍然更新）
# --------------------
def drop_claw():
    global hits_remaining, game_state, current_level_index, lives

    if game_state != "PLAYING":
        return

    # 下落动画
    for step in range(DROP_STEPS + 1):
        offset = step * DROP_STEP_PIXELS
        set_claw_y(offset)

        if difficulty == "MEDIUM":
            update_medium_balls()
        elif difficulty == "HARD":
            update_hard_balls()

        time.sleep(0.03)

    # 底部检测是否命中
    if difficulty == "EASY":
        hit = check_hit_easy()
    elif difficulty == "MEDIUM":
        hit = check_hit_medium()
    else:  # HARD
        hit = check_hit_hard()

    if hit:
        sfx_hit()

        # 🔹 EASY 模式：每次命中后随机一个新位置
        if difficulty == "EASY":
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
        if difficulty in ("MEDIUM", "HARD"):
            lives -= 1
            if lives < 0:
                lives = 0
            update_health_bar()
            if lives == 0:
                game_state = "GAME_OVER"
                message_label.text = "GAME OVER"
                sfx_game_over()

    # ... keep the rest of drop_claw (pause + raise claw) the same ...

    # 底部停一下
    time.sleep(0.15)

    # 收爪子回去
    for step in range(DROP_STEPS, -1, -1):
        offset = step * DROP_STEP_PIXELS
        set_claw_y(offset)

        # 回升时也继续更新球
        if difficulty == "MEDIUM":
            update_medium_balls()
        elif difficulty == "HARD":
            update_hard_balls()

        time.sleep(0.03)


# --------------------
# 初始化：先显示菜单
# --------------------
show_menu()

# --------------------
# 主循环
# --------------------
while True:
    # 读按钮（下降沿）
    current_btn = rot_btn.value
    button_pressed = last_btn_state and (not current_btn)
    last_btn_state = current_btn

    # 读旋钮 A 相位（只在菜单用来换选项）
    current_rot_a = rot_a.value
    if in_menu and (current_rot_a != rot_last_state):
        # 用 A 的下降沿，配合 B 判断方向
        if not current_rot_a:
            if rot_b.value:
                menu_index += 1
            else:
                menu_index -= 1

            # wrap
            if menu_index < 0:
                menu_index = len(DIFFICULTY_OPTIONS) - 1
            if menu_index >= len(DIFFICULTY_OPTIONS):
                menu_index = 0

            # 更新中间那一行 "< EASY >"
            current_name = DIFFICULTY_OPTIONS[menu_index]
            message_label.text = f"< {current_name} >"

        rot_last_state = current_rot_a

    # --------- 菜单逻辑 ----------
    if in_menu:
        # 按钮：开始对应难度
        if button_pressed:
            in_menu = False
            if DIFFICULTY_OPTIONS[menu_index] == "EASY":
                start_easy()
            elif DIFFICULTY_OPTIONS[menu_index] == "MEDIUM":
                start_medium()
            elif DIFFICULTY_OPTIONS[menu_index] == "HARD":
                start_hard()
        time.sleep(0.02)
        continue

    # --------- 游戏逻辑 ----------
    now = time.monotonic()
    elapsed = now - round_start_time
    remaining = time_limit - elapsed
    if remaining < 0:
        remaining = 0.0

    # 更新倒计时显示
    timer_label.text = f"{remaining:4.1f}"

    # 时间到了且还没完成当前关卡目标 → Game Over
    if game_state == "PLAYING" and remaining <= 0 and hits_remaining > 0:
        game_state = "GAME_OVER"
        message_label.text = "GAME OVER"

    # MEDIUM/HARD 模式更新球（正常帧更新）
    if game_state == "PLAYING":
        if difficulty == "MEDIUM":
            update_medium_balls()
        elif difficulty == "HARD":
            update_hard_balls()
   
    # 读取加速度计并做校正 + 滤波
    raw_x, raw_y, raw_z = accelerometer.acceleration

    # 去掉静态偏移（校准得到的 offset_x）
    centered_x = raw_x - offset_x

    # 对 X 做指数移动平均滤波，减少抖动
    filtered_x = ACCEL_ALPHA * centered_x + (1.0 - ACCEL_ALPHA) * filtered_x

    # 用滤波后的 X 值映射到水平位置
    claw_x = int(
        map_range(
            filtered_x,
            ACCEL_MIN, ACCEL_MAX,
            0, SCREEN_WIDTH - CLAW_WIDTH,
        )
    )
    # 侧向移动爪子
    claw_line1.x = claw_x
    claw_line2.x = claw_x
    claw_line3.x = claw_x

    # 按钮：在 PLAYING 状态才允许下爪 / 在结束后按返回菜单
    if button_pressed:
        if game_state == "PLAYING" and remaining > 0:
            drop_claw()
        elif game_state in ("GAME_OVER", "WIN"):
            show_menu()

    time.sleep(0.02)