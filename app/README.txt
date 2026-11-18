MSIG 1.0.9 for Mac - algorithm editor for the DSP7000

Compatibility: tested only on the author's own DSP7000. Other units and models
have not been tested.

IMPORTANT NOTICE
MSIG is an independent project by Moteka (motekamusic.com).
- It is not associated with, endorsed by or supported by Eventide Inc., which is
  not responsible for any issue that may occur when MSIG is used with its products.
- MSIG contains no software, data or other material from the hardware
  manufacturer. The module list it needs is read from your own unit.
- All product names belong to their respective owners.
MSIG is provided "as is", without warranty of any kind. Back up your unit's
programs before sending anything to it. You use MSIG at your own risk.

REQUIREMENTS
- Intel Mac with macOS 10.13 or later, or Apple Silicon Mac with macOS 11 or later.
- USB-serial adapter and a straight-through DB9 cable (not null-modem).
  FTDI adapters work out of the box; Prolific (PL2303) or CH340 adapters
  may need the manufacturer's driver.
- On the DSP: serial link at 115200 baud with 2 stop bits, SysEx on, MIDI
  device ID 1.
- Nothing else to install: MSIG includes everything it needs.

INSTALLATION
1. Drag MSIG into the Applications folder.
2. Double-click MSIG. The app is signed and notarized by Apple;
   macOS only asks for confirmation the first time it is opened.

FIRST USE
1. Launch MSIG: the editor opens in its own window, with the File, Edit, DSP
   and Window menus in the menu bar.
2. Choose the serial port, then click "Connect". MSIG connects by itself
   only to USB-serial adapters (/dev/cu.usbserial...); "usbmodem" ports
   (USB-MIDI devices, sound cards) are listed but must be chosen by hand.
3. First time only: click "Load module database". This takes
   about 30 seconds on a DSP7000 and can take several minutes on units with a
   larger database; the progress is shown at the bottom of the window.
   The module list is read from your DSP and kept on the Mac.

MENUS AND SHORTCUTS
- File: New (Cmd N), Random Patch (Cmd R), Random Patch from Seed
  (Shift Cmd R), Open (Cmd O), Save (Cmd S), Save As (Shift Cmd S),
  Rename Patch, Close Window (Cmd W).
- Edit: Undo (Cmd Z), Redo (Shift Cmd Z), Cut, Copy, Paste, Duplicate (Cmd D)
  and Delete act on the selected module; Select All (Cmd A).
- DSP: Connect, Get Algorithm (Cmd G), Send to DSP, Screen, Load Module
  Database, Import Module Database File, Auto Layout (Cmd L).
- Closing the window (or Cmd Q) quits MSIG and releases the serial port; MSIG
  asks first if the patch has unsaved changes.

EDITING A PATCH
- Patch name: click it next to the MSIG title (or File > Rename Patch...).
- Click a module to show its parameters in the inspector.
- Cables: drag from a coloured dot to another to connect two modules (only
  compatible signal types light up). Double-click an input dot to unplug it;
  double-click an output dot to remove all its cables. Cmd Z undoes any change.
- File > Save writes the .sig file; Save As asks for a new name and place.
- "Send to DSP" replaces the algorithm loaded on the unit: save it first.

RANDOM PATCHES
- File > Random Patch (Cmd R) creates a random but playable patch, 100% wet,
  in one of eight characters (ambient, glitch, shimmer, motion, dirty, echo,
  metal, lofi).
- Its name gives the seed: File > Random Patch from Seed (Shift Cmd R) gets
  the same patch again.
- Each random patch has a "level" knob and a few parameter knobs on its
  "random" menu page on the DSP.

FILES AND LOGS
- Patches: .sig text files, saved wherever you choose (Documents by default).
- Module list read from your unit: ~/Library/Application Support/MSIG/
- Log: ~/Library/Logs/MSIG.log

TROUBLESHOOTING
- No serial port in the list: check the adapter and its driver, then unplug
  and plug it in again.
- No answer from the DSP: check the cable (straight-through, not null-modem),
  115200 baud, SysEx on and MIDI device ID 1 on the unit.
- "Reply arrived garbled" on Get algorithm or Screen: the serial settings of
  the unit and of MSIG do not match. Check first that the unit's stop bits
  match MSIG's (2 by default; an H8000 set to 1 stop bit gives exactly this),
  then that the speeds are the same. Both are chosen next to the serial port
  menu, applied when you click Connect/Reconnect, and remembered.
- Empty module list: click "Load module database" once, while connected.
- Module database from a file instead of the unit: "Import database..."
  accepts a text database file (.sbf, as saved by the old Windows editor) or
  a SysEx dump (.syx). A .sbf file placed in
  ~/Library/Application Support/MSIG
  is also picked up automatically at startup when no database is loaded.
  Use the database that matches the software version of your unit.
- "port busy": another program (or another copy of MSIG) uses the port.
- Any other problem: see ~/Library/Logs/MSIG.log.

Version 1.0.9 - (c) Moteka - motekamusic.com / Free software. Not for resale.
