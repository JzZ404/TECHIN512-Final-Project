# TECHIN512-Final-Project
**Overview**

This project reimagines the arcade claw machine as a handheld embedded game using the Xiao ESP32C3 and CircuitPython. Instead of controlling a physical claw, players operate a digital claw displayed on the OLED screen. The rotary encoder functions like the joystick found on real claw machines, allowing players to slide the claw horizontally and press down to perform a “grab.”

The game features three difficulty levels, each introducing new mechanics and increasing pressure:

- Easy Mode: The target remains stationary, and the player has a simple time limit to grab it.
- Medium Mode: The claw is still stationary, but a life system is introduced — the player can only miss up to three times before receiving a Game Over.
- Hard Mode: The target moves across the screen, and the player must capture a set number of targets within the time limit while still managing the three-life system.

Across all levels, players receive feedback through the OLED display and buzzer, while the NeoPixel provides visual cues for events such as successful grabs, missed attempts, or game start. The game includes both Game Over and Game Win screens, and players can restart immediately without power cycling the device.

**Hardware Used**

| Component                | How It Was Used                                                                 |
|--------------------------|----------------------------------------------------------------------------------|
| **Xiao ESP323C Microcontroller**     | Main controller running all game logic in CircuitPython.                         |
| **SSD1306 128×64 OLED**  | Displays UI: claw position, target, timer, difficulty menu, win/lose.    |
| **Rotary Encoder**       | Acts as joystick: rotate to move claw; press to grab.                           |
| **ADXL345 Accelerometer**| Calibrated/filtered to meet project requirements; integrated for motion sensing.|
| **NeoPixel LED**         | Visual feedback: start, success, miss, game over indicators.                    |
| **Piezo Buzzer**         | Plays tones for events (grab success, miss, game start, game over).             |
| **LiPo Battery**         | Powers the device for portable gameplay.                                        |
| **On/Off Switch**        | Mounted externally for quick power control.                                     |


**Enclosure Design**

The enclosure was designed to look and feel like a miniature table-top claw machine, combining a transparent display chamber with a retro-styled control base. The design focuses on aesthetics, ergonomics, and serviceability while securely housing all electronics.

Arcade-Inspired Upper Chamber
- The top portion mimics the iconic glass box of real claw machines.
- Clear acrylic panels were fitted into a 3D-printed frame, allowing players to “peek inside” and see plush mini-toys.
- Although decorative, this chamber reinforces the theme and makes the device instantly recognizable as a claw machine.

Retro Control Console
- The bottom half of the enclosure uses a contrasting pink front panel, giving it a playful arcade feel.
- The OLED screen is positioned on the left, just like status screens on commercial claw machines.
- Rotary Encoder is placed on the left for controlling the claw movement and grab action
- Push Button is placed on the right for triggers

Internal Layout & Electronics Housing
- The angled lower enclosure provides enough volume for the electronics.
- Components are arranged so the rotary encoder and screen mount cleanly through the front panel.
- Female headers were used so every component can be removed for debugging or replacement.
- A dedicated USB-C port cutout allows programming and charging without opening the case.
- The enclosure can be opened via the bottom/lower section for quick access to electronics.

Material List
- PLA
- TPU
- Carbon Fiber PLA
- Acrylic Panels
- Cotton Filling



