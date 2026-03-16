/*
 * Lineage Classic Automation - Arduino Leonardo HID Controller
 *
 * Receives commands via Serial and executes them as HID
 * (keyboard/mouse) inputs. Arduino Leonardo has native USB HID support.
 *
 * Protocol (text-based, newline terminated):
 *   CLICK x y         - Move mouse to (x,y) and click
 *   DBLCLICK x y      - Move mouse to (x,y) and double-click
 *   TYPE text          - Type text string
 *   KEY keyname        - Press and release a key
 *   HOTKEY key1+key2   - Press key combination
 *   MOVE x y           - Move mouse to absolute position
 *
 * Supported key names:
 *   tab, enter, esc, backspace, delete, space,
 *   up, down, left, right, f1-f12, ctrl, alt, shift
 */

#include <Mouse.h>
#include <Keyboard.h>

// Screen resolution (adjust to match your display)
int screenWidth = 1920;
int screenHeight = 1080;

// Current mouse position tracking
int currentX = screenWidth / 2;
int currentY = screenHeight / 2;

String inputBuffer = "";

void setup() {
  Serial.begin(9600);
  Mouse.begin();
  Keyboard.begin();

  // Center mouse
  resetMousePosition();

  Serial.println("READY");
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (inputBuffer.length() > 0) {
        processCommand(inputBuffer);
        inputBuffer = "";
      }
    } else {
      inputBuffer += c;
    }
  }
}

void processCommand(String cmd) {
  cmd.trim();

  if (cmd.startsWith("CLICK ")) {
    handleClick(cmd.substring(6), false);
  }
  else if (cmd.startsWith("DBLCLICK ")) {
    handleClick(cmd.substring(9), true);
  }
  else if (cmd.startsWith("TYPE ")) {
    handleType(cmd.substring(5));
  }
  else if (cmd.startsWith("KEY ")) {
    handleKey(cmd.substring(4));
  }
  else if (cmd.startsWith("HOTKEY ")) {
    handleHotkey(cmd.substring(7));
  }
  else if (cmd.startsWith("MOVE ")) {
    handleMove(cmd.substring(5));
  }
  else {
    Serial.println("ERR:UNKNOWN");
    return;
  }

  Serial.println("OK");
}

void handleClick(String params, bool doubleClick) {
  int spaceIdx = params.indexOf(' ');
  if (spaceIdx < 0) {
    Serial.println("ERR:PARAMS");
    return;
  }

  int targetX = params.substring(0, spaceIdx).toInt();
  int targetY = params.substring(spaceIdx + 1).toInt();

  moveMouseAbsolute(targetX, targetY);
  delay(50);

  Mouse.click(MOUSE_LEFT);
  if (doubleClick) {
    delay(80);
    Mouse.click(MOUSE_LEFT);
  }
}

void handleType(String text) {
  for (int i = 0; i < text.length(); i++) {
    Keyboard.write(text.charAt(i));
    delay(30);
  }
}

void handleKey(String keyName) {
  uint8_t key = resolveKey(keyName);
  if (key > 0) {
    Keyboard.press(key);
    delay(50);
    Keyboard.release(key);
  }
}

void handleHotkey(String combo) {
  // Parse key1+key2+key3...
  uint8_t keys[4];
  int keyCount = 0;

  int start = 0;
  while (start < combo.length() && keyCount < 4) {
    int plusIdx = combo.indexOf('+', start);
    String keyStr;
    if (plusIdx < 0) {
      keyStr = combo.substring(start);
      start = combo.length();
    } else {
      keyStr = combo.substring(start, plusIdx);
      start = plusIdx + 1;
    }
    keyStr.trim();
    uint8_t key = resolveKey(keyStr);
    if (key > 0) {
      keys[keyCount++] = key;
    }
  }

  // Press all keys
  for (int i = 0; i < keyCount; i++) {
    Keyboard.press(keys[i]);
    delay(30);
  }
  delay(50);
  // Release all keys in reverse
  for (int i = keyCount - 1; i >= 0; i--) {
    Keyboard.release(keys[i]);
    delay(30);
  }
}

void handleMove(String params) {
  int spaceIdx = params.indexOf(' ');
  if (spaceIdx < 0) return;

  int targetX = params.substring(0, spaceIdx).toInt();
  int targetY = params.substring(spaceIdx + 1).toInt();

  moveMouseAbsolute(targetX, targetY);
}

void moveMouseAbsolute(int targetX, int targetY) {
  /*
   * Arduino Mouse library uses relative movement.
   * Strategy: reset to (0,0) by moving far negative,
   * then move to target position in steps.
   */

  // Move to origin (0,0) - overshoot to ensure we're at corner
  for (int i = 0; i < 20; i++) {
    Mouse.move(-127, -127, 0);
    delay(2);
  }
  currentX = 0;
  currentY = 0;

  // Move to target in steps of 127 (max per move call)
  int remainX = targetX;
  int remainY = targetY;

  while (remainX > 0 || remainY > 0) {
    int dx = min(remainX, 127);
    int dy = min(remainY, 127);
    Mouse.move(dx, dy, 0);
    remainX -= dx;
    remainY -= dy;
    delay(2);
  }

  currentX = targetX;
  currentY = targetY;
}

void resetMousePosition() {
  // Move mouse far to top-left corner to establish known position
  for (int i = 0; i < 30; i++) {
    Mouse.move(-127, -127, 0);
    delay(2);
  }
  currentX = 0;
  currentY = 0;
}

uint8_t resolveKey(String keyName) {
  keyName.toLowerCase();
  keyName.trim();

  if (keyName == "tab") return KEY_TAB;
  if (keyName == "enter" || keyName == "return") return KEY_RETURN;
  if (keyName == "esc" || keyName == "escape") return KEY_ESC;
  if (keyName == "backspace") return KEY_BACKSPACE;
  if (keyName == "delete" || keyName == "del") return KEY_DELETE;
  if (keyName == "space") return ' ';
  if (keyName == "up") return KEY_UP_ARROW;
  if (keyName == "down") return KEY_DOWN_ARROW;
  if (keyName == "left") return KEY_LEFT_ARROW;
  if (keyName == "right") return KEY_RIGHT_ARROW;
  if (keyName == "ctrl" || keyName == "control") return KEY_LEFT_CTRL;
  if (keyName == "alt") return KEY_LEFT_ALT;
  if (keyName == "shift") return KEY_LEFT_SHIFT;
  if (keyName == "f1") return KEY_F1;
  if (keyName == "f2") return KEY_F2;
  if (keyName == "f3") return KEY_F3;
  if (keyName == "f4") return KEY_F4;
  if (keyName == "f5") return KEY_F5;
  if (keyName == "f6") return KEY_F6;
  if (keyName == "f7") return KEY_F7;
  if (keyName == "f8") return KEY_F8;
  if (keyName == "f9") return KEY_F9;
  if (keyName == "f10") return KEY_F10;
  if (keyName == "f11") return KEY_F11;
  if (keyName == "f12") return KEY_F12;

  // Single character
  if (keyName.length() == 1) {
    return keyName.charAt(0);
  }

  return 0;
}
