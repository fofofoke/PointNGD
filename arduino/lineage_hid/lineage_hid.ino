/*
 * Lineage Classic Automation - Arduino Leonardo HID Controller
 *
 * Receives commands via Serial and executes them as HID
 * (keyboard/mouse) inputs. Arduino Leonardo has native USB HID support.
 *
 * REQUIRES: HID-Project library (install via Arduino Library Manager)
 *   Sketch -> Include Library -> Manage Libraries -> search "HID-Project"
 *
 * Uses AbsoluteMouse for precise pixel-accurate positioning.
 * The PC sends a SCREEN command on connect to set the coordinate mapping.
 *
 * Protocol (text-based, newline terminated):
 *   CLICK x y         - Move mouse to (x,y) and click
 *   DBLCLICK x y      - Move mouse to (x,y) and double-click
 *   TYPE text          - Type text string
 *   KEY keyname        - Press and release a key
 *   HOTKEY key1+key2   - Press key combination
 *   MOVE x y           - Move mouse to absolute position
 *   SCREEN ox oy w h   - Set virtual desktop origin and dimensions
 *
 * Supported key names:
 *   tab, enter, esc, backspace, delete, space,
 *   up, down, left, right, f1-f12, ctrl, alt, shift
 */

#include <HID-Project.h>

// Virtual desktop dimensions (updated by SCREEN command from PC)
long screenOriginX = 0;
long screenOriginY = 0;
long screenWidth = 1920;
long screenHeight = 1080;

// Current mouse position tracking
int currentX = 0;
int currentY = 0;

String inputBuffer = "";

void setup() {
  Serial.begin(9600);
  AbsoluteMouse.begin();
  Keyboard.begin();

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
      if (inputBuffer.length() < 256) {
        inputBuffer += c;
      }
    }
  }
}

void processCommand(String cmd) {
  cmd.trim();

  bool success;

  if (cmd.startsWith("CLICK ")) {
    success = handleClick(cmd.substring(6), false);
  }
  else if (cmd.startsWith("DBLCLICK ")) {
    success = handleClick(cmd.substring(9), true);
  }
  else if (cmd.startsWith("TYPE ")) {
    success = handleType(cmd.substring(5));
  }
  else if (cmd.startsWith("KEY ")) {
    success = handleKey(cmd.substring(4));
  }
  else if (cmd.startsWith("HOTKEY ")) {
    success = handleHotkey(cmd.substring(7));
  }
  else if (cmd.startsWith("MOVE ")) {
    success = handleMove(cmd.substring(5));
  }
  else if (cmd.startsWith("SCREEN ")) {
    success = handleScreen(cmd.substring(7));
  }
  else {
    Serial.println("ERR:UNKNOWN");
    return;
  }

  if (success) {
    Serial.println("OK");
  }
}

bool handleScreen(String params) {
  // Parse "originX originY width height"
  int idx1 = params.indexOf(' ');
  if (idx1 < 0) { Serial.println("ERR:PARAMS"); return false; }
  int idx2 = params.indexOf(' ', idx1 + 1);
  if (idx2 < 0) { Serial.println("ERR:PARAMS"); return false; }
  int idx3 = params.indexOf(' ', idx2 + 1);
  if (idx3 < 0) { Serial.println("ERR:PARAMS"); return false; }

  screenOriginX = params.substring(0, idx1).toInt();
  screenOriginY = params.substring(idx1 + 1, idx2).toInt();
  screenWidth = params.substring(idx2 + 1, idx3).toInt();
  screenHeight = params.substring(idx3 + 1).toInt();

  if (screenWidth <= 0) screenWidth = 1920;
  if (screenHeight <= 0) screenHeight = 1080;

  return true;
}

bool handleClick(String params, bool doubleClick) {
  int spaceIdx = params.indexOf(' ');
  if (spaceIdx < 0) {
    Serial.println("ERR:PARAMS");
    return false;
  }

  int targetX = params.substring(0, spaceIdx).toInt();
  int targetY = params.substring(spaceIdx + 1).toInt();

  moveMouseAbsolute(targetX, targetY);
  delay(50);

  AbsoluteMouse.click(MOUSE_LEFT);
  if (doubleClick) {
    delay(80);
    AbsoluteMouse.click(MOUSE_LEFT);
  }
  return true;
}

bool handleType(String text) {
  for (unsigned int i = 0; i < text.length(); i++) {
    Keyboard.write(text.charAt(i));
    delay(30);
  }
  return true;
}

bool handleKey(String keyName) {
  uint8_t key = resolveKey(keyName);
  if (key == 0) {
    Serial.println("ERR:UNKNOWN_KEY");
    return false;
  }
  Keyboard.press(key);
  delay(50);
  Keyboard.release(key);
  return true;
}

bool handleHotkey(String combo) {
  // Parse key1+key2+key3...
  uint8_t keys[4];
  int keyCount = 0;

  int start = 0;
  while (start < (int)combo.length() && keyCount < 4) {
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

  if (keyCount == 0) {
    Serial.println("ERR:NO_KEYS");
    return false;
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
  return true;
}

bool handleMove(String params) {
  int spaceIdx = params.indexOf(' ');
  if (spaceIdx < 0) {
    Serial.println("ERR:PARAMS");
    return false;
  }

  int targetX = params.substring(0, spaceIdx).toInt();
  int targetY = params.substring(spaceIdx + 1).toInt();

  moveMouseAbsolute(targetX, targetY);
  return true;
}

void moveMouseAbsolute(int targetX, int targetY) {
  /*
   * Convert screen pixel coordinates to HID absolute range (0-32767).
   * Windows maps HID absolute coordinates to the virtual desktop
   * (the combined area of all monitors).
   *
   * The PC sends SCREEN originX originY width height on connect,
   * so we know the virtual desktop dimensions.
   */
  long absX = ((long)(targetX - screenOriginX) * 32767L) / screenWidth;
  long absY = ((long)(targetY - screenOriginY) * 32767L) / screenHeight;

  // Clamp to valid range
  absX = constrain(absX, 0, 32767);
  absY = constrain(absY, 0, 32767);

  AbsoluteMouse.moveTo(absX, absY);

  currentX = targetX;
  currentY = targetY;
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
