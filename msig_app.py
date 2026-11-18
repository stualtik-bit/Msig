#!/usr/bin/env python3
"""
msig_app.py - MSIG in its own macOS window.

The editor (the same HTML file as the browser version) is shown in a WKWebView window,
with a real menu bar (File, Edit, DSP, Window) and the native dialogs.
The msig_serveur.py gateway runs in the same process, on a randomly chosen local port
protected by the origin check; closing the window quits the application and releases
the serial port.

    python3 msig_app.py                       # native window
    python3 msig_app.py --port /dev/cu.xxx    # forced serial port
    python3 msig_app.py --browser [options]   # old version: editor in the browser

MSIG_SELFTEST=/path/result.json: automatic test (see selftest()), then quit.
"""
import json
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import msig_serveur as gw  # noqa: E402

if "--browser" in sys.argv or "--http" in sys.argv or "--no-browser" in sys.argv:
    sys.argv = [a for a in sys.argv if a != "--browser"]
    gw.main()
    sys.exit(0)

import objc  # noqa: E402
from Foundation import NSObject, NSURL, NSURLRequest, NSMakeRect  # noqa: E402
from AppKit import (  # noqa: E402
    NSApplication, NSWindow, NSMenu, NSMenuItem, NSAlert, NSTextField, NSSavePanel, NSOpenPanel,
    NSApplicationActivationPolicyRegular, NSWindowStyleMaskTitled, NSWindowStyleMaskClosable,
    NSWindowStyleMaskMiniaturizable, NSWindowStyleMaskResizable, NSBackingStoreBuffered,
    NSEventModifierFlagCommand, NSEventModifierFlagShift, NSEventModifierFlagOption,
    NSAlertFirstButtonReturn, NSModalResponseOK, NSTerminateNow, NSTerminateCancel,
    NSBitmapImageRep, NSPNGFileType,
)
from WebKit import (  # noqa: E402
    WKWebView, WKWebViewConfiguration, WKUserContentController, WKUserScript,
    WKUserScriptInjectionTimeAtDocumentStart,
)
from PyObjCTools import AppHelper  # noqa: E402

SELFTEST = os.environ.get("MSIG_SELFTEST")
APP = NSApplication.sharedApplication


def _protocols(*names):
    out = []
    for n in names:
        try:
            out.append(objc.protocolNamed(n))
        except Exception:
            pass
    return out
CMD, SHIFT, OPT = NSEventModifierFlagCommand, NSEventModifierFlagShift, NSEventModifierFlagOption

# Tells the application whether a text field has focus (Edit commands then act on the
# text, as in any Mac application); injected before the page loads.
FOCUS_JS = """
(function () {
  const post = m => window.webkit.messageHandlers.msig.postMessage(m);
  const isText = el => !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable);
  document.addEventListener("focusin", e => post({ type: "focus", text: isText(e.target) }), true);
  document.addEventListener("focusout", () => setTimeout(() => post({ type: "focus", text: isText(document.activeElement) }), 0), true);
})();
"""

NATIVE_EDIT = {"undo": "undo:", "redo": "redo:", "cut": "cut:", "copy": "copy:", "paste": "paste:", "selectAll": "selectAll:"}


def setup_log():
    if gw.BUNDLE:  # application without a terminal: messages go to ~/Library/Logs/MSIG.log
        gw.open_log("(window)")
    else:
        print(time.strftime("--- %Y-%m-%d %H:%M:%S"), "MSIG", gw.VERSION, "(window)")


def start_gateway(serial_port):
    bridge = gw.Bridge(115200, 1)
    beat = [time.time()]
    srv = gw.ThreadingHTTPServer(("127.0.0.1", 0), gw.BaseHTTPRequestHandler)
    http_port = srv.server_address[1]
    srv.RequestHandlerClass = gw.make_handler(bridge, gw.find_editor(), http_port, beat)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = serial_port or gw.auto_port()
    if port:
        try:
            bridge.connect(port)
            print(f"DSP on {port} at {bridge.baud} baud.")
        except Exception as e:
            print(f"{e} (choose the port in the editor)")
    return srv, bridge, f"http://127.0.0.1:{http_port}/"


def on_main_and_wait(start):
    """Run start(done) on the main thread; done(value) unblocks the caller."""
    ev, box = threading.Event(), {}

    def done(v):
        box["v"] = v
        ev.set()

    def run():
        try:
            start(done)
        except Exception as e:  # the dialog could not be opened
            print("dialog error:", e)
            done(None)
    AppHelper.callAfter(run)
    ev.wait()
    return box.get("v")


# The page's questions (confirm, prompt) are in-page HTML dialogs: the window does not
# need WebKit's JavaScript delegates.
class Controller(NSObject, protocols=_protocols("WKUIDelegate", "WKNavigationDelegate", "WKScriptMessageHandler")):
    def init(self):
        self = objc.super(Controller, self).init()
        self.text_focus = False
        self.dirty = False
        self.window = None
        self.web = None
        self.bridge = None
        self.srv = None
        self.selftest_log = []
        return self

    # ---------------------------------------------------------------- window
    @objc.python_method
    def build(self, url):
        cfg = WKWebViewConfiguration.alloc().init()
        ucc = WKUserContentController.alloc().init()
        ucc.addScriptMessageHandler_name_(self, "msig")
        ucc.addUserScript_(WKUserScript.alloc().initWithSource_injectionTime_forMainFrameOnly_(
            FOCUS_JS, WKUserScriptInjectionTimeAtDocumentStart, True))
        cfg.setUserContentController_(ucc)
        style = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskMiniaturizable | NSWindowStyleMaskResizable
        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 1280, 820), style, NSBackingStoreBuffered, False)
        self.window.setTitle_("MSIG")
        self.window.setMinSize_((760, 480))
        self.window.center()
        self.window.setFrameAutosaveName_("MSIG main window")
        self.window.setDelegate_(self)
        self.window.setReleasedWhenClosed_(False)
        self.web = WKWebView.alloc().initWithFrame_configuration_(self.window.contentView().bounds(), cfg)
        self.web.setUIDelegate_(self)
        self.web.setNavigationDelegate_(self)
        self.web.setAutoresizingMask_(18)  # width and height follow the window
        self.window.contentView().addSubview_(self.web)
        self.web.loadRequest_(NSURLRequest.requestWithURL_(NSURL.URLWithString_(url)))
        self.window.makeKeyAndOrderFront_(None)

    @objc.python_method
    def js(self, code, cb=None):
        self.web.evaluateJavaScript_completionHandler_(code, cb)

    # ---------------------------------------------------------------- menus
    def menuAction_(self, sender):
        act = sender.representedObject()
        if act in NATIVE_EDIT and (self.text_focus or act == "selectAll"):
            APP().sendAction_to_from_(NATIVE_EDIT[act], None, sender)
            return
        self.js("window.msigMenu && msigMenu(%s)" % json.dumps(act))

    @objc.python_method
    def build_menus(self):
        main = NSMenu.alloc().init()

        def add_menu(title, items):
            top = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, None, "")
            sub = NSMenu.alloc().initWithTitle_(title)
            for it in items:
                if it is None:
                    sub.addItem_(NSMenuItem.separatorItem())
                    continue
                label, act = it[0], it[1]
                key = it[2] if len(it) > 2 else ""
                mods = it[3] if len(it) > 3 else CMD
                if act.endswith(":"):  # standard Cocoa action
                    mi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(label, act, key)
                else:
                    mi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(label, "menuAction:", key)
                    mi.setRepresentedObject_(act)
                    mi.setTarget_(self)
                if key:
                    mi.setKeyEquivalentModifierMask_(mods)
                sub.addItem_(mi)
            top.setSubmenu_(sub)
            main.addItem_(top)
            return sub

        add_menu("MSIG", [("About MSIG", "orderFrontStandardAboutPanel:"), None,
                          ("Hide MSIG", "hide:", "h"), ("Hide Others", "hideOtherApplications:", "h", CMD | OPT),
                          ("Show All", "unhideAllApplications:"), None, ("Quit MSIG", "terminate:", "q")])
        add_menu("File", [("New…", "new", "n"), ("Random Patch", "random", "r"),
                          ("Random Patch from Seed…", "randomSeed", "r", CMD | SHIFT), None,
                          ("Open…", "open", "o"), None, ("Save", "save", "s"), ("Save As…", "saveAs", "s", CMD | SHIFT),
                          None, ("Rename Patch…", "rename"), None, ("Close Window", "performClose:", "w")])
        add_menu("Edit", [("Undo", "undo", "z"), ("Redo", "redo", "z", CMD | SHIFT), None,
                          ("Cut", "cut", "x"), ("Copy", "copy", "c"), ("Paste", "paste", "v"),
                          ("Duplicate", "duplicate", "d"), ("Delete", "delete"), None, ("Select All", "selectAll", "a")])
        add_menu("DSP", [("Connect", "connect"), ("Get Algorithm", "get", "g"), ("Send to DSP…", "send"), None,
                         ("Screen", "screen"), None, ("Load Module Database", "dbase"),
                         ("Import Module Database File…", "dbaseFile"), None, ("Auto Layout", "layout", "l")])
        win = add_menu("Window", [("Minimize", "performMiniaturize:", "m"), ("Zoom", "performZoom:"), None,
                                  ("Bring All to Front", "arrangeInFront:")])
        APP().setMainMenu_(main)
        APP().setWindowsMenu_(win)

    # ---------------------------------------------------------------- page messages
    def userContentController_didReceiveScriptMessage_(self, ucc, msg):
        m = msg.body()
        t = m.get("type") if hasattr(m, "get") else None
        if t == "focus":
            self.text_focus = bool(m.get("text"))
        elif t == "state":
            name = m.get("title") or "untitled"
            self.dirty = bool(m.get("dirty"))
            self.window.setTitle_(f"{name} — MSIG")
            self.window.setDocumentEdited_(self.dirty)

    # ---------------------------------------------------------------- native alert (closing)
    @objc.python_method
    def _alert(self, text, buttons, field=None):
        a = NSAlert.alloc().init()
        a.setMessageText_(str(text))
        for b in buttons:
            a.addButtonWithTitle_(b)
        if field is not None:
            a.setAccessoryView_(field)
            a.window().setInitialFirstResponder_(field)
        return a.runModal() == NSAlertFirstButtonReturn

    # ---------------------------------------------------------------- Open / Save (window sheets)
    @objc.python_method
    def ask_save(self, name, folder):
        def start(done):
            p = NSSavePanel.savePanel()
            p.setNameFieldStringValue_(name)
            p.setAllowedFileTypes_(["sig"])
            p.setAllowsOtherFileTypes_(True)
            p.setDirectoryURL_(NSURL.fileURLWithPath_(self._folder(folder)))
            p.beginSheetModalForWindow_completionHandler_(
                self.window, lambda r: done(p.URL().path() if r == NSModalResponseOK else None))
        return on_main_and_wait(start)

    @objc.python_method
    def ask_open(self, folder):
        def start(done):
            p = NSOpenPanel.openPanel()
            p.setAllowedFileTypes_(["sig", "txt"])
            p.setDirectoryURL_(NSURL.fileURLWithPath_(self._folder(folder)))
            p.beginSheetModalForWindow_completionHandler_(
                self.window, lambda r: done(p.URLs()[0].path() if r == NSModalResponseOK and p.URLs() else None))
        return on_main_and_wait(start)

    @objc.python_method
    def ask_open_dbase(self, folder):
        def start(done):
            p = NSOpenPanel.openPanel()
            p.setMessage_("Module database file (.sbf, .syx)")
            p.setAllowedFileTypes_(["sbf", "syx", "txt"])
            p.setAllowsOtherFileTypes_(True)
            p.setDirectoryURL_(NSURL.fileURLWithPath_(self._folder(folder or "~/Downloads")))
            p.beginSheetModalForWindow_completionHandler_(
                self.window, lambda r: done(p.URLs()[0].path() if r == NSModalResponseOK and p.URLs() else None))
        return on_main_and_wait(start)

    @objc.python_method
    def _folder(self, folder):
        f = os.path.expanduser(folder or "")
        return f if os.path.isdir(f) else os.path.expanduser("~/Documents")

    # ---------------------------------------------------------------- closing
    @objc.python_method
    def _confirm_discard(self):
        if not self.dirty or SELFTEST:
            return True
        return self._alert("This patch has unsaved changes. Close it anyway?", ["Discard Changes", "Cancel"])

    def windowShouldClose_(self, win):
        ok = self._confirm_discard()
        if ok:
            self.dirty = False
        return ok

    def applicationShouldTerminateAfterLastWindowClosed_(self, app):
        return True

    def applicationShouldTerminate_(self, app):
        if self._confirm_discard():
            self.dirty = False
            return NSTerminateNow
        return NSTerminateCancel

    def applicationWillTerminate_(self, note):
        try:
            if self.bridge and self.bridge.dev:
                self.bridge.dev.link.close()
                print("serial port closed")
        except Exception as e:
            print("close:", e)

    def applicationShouldHandleReopen_hasVisibleWindows_(self, app, visible):
        if self.window and not visible:
            self.window.makeKeyAndOrderFront_(None)
        return True

    # ---------------------------------------------------------------- automatic test
    def webView_didFinishNavigation_(self, wv, nav):
        if SELFTEST:
            AppHelper.callLater(2.0, self.selftest)

    @objc.python_method
    def selftest(self):
        steps = []

        def finish():
            def snap(img, err):
                path = SELFTEST.replace(".json", ".png")
                try:
                    rep = NSBitmapImageRep.imageRepWithData_(img.TIFFRepresentation())
                    rep.representationUsingType_properties_(NSPNGFileType, {}).writeToFile_atomically_(path, True)
                except Exception as e:
                    steps.append(["snapshot error", str(e)])
                with open(SELFTEST, "w") as f:
                    json.dump({"steps": steps, "dialogs": self.selftest_log, "title": str(self.window.title()),
                               "edited": bool(self.window.isDocumentEdited())}, f, indent=1)
                APP().terminate_(None)
            self.web.takeSnapshotWithConfiguration_completionHandler_(None, snap)

        probe = """JSON.stringify({ native: typeof NATIVE !== 'undefined' && NATIVE, defs: Object.keys(DEFS).length,
          mods: doc.mods.length, name: patchName(), hist: hist.i, quitHidden: getComputedStyle($('bQuit')).display === 'none',
          editMenuHidden: getComputedStyle(document.querySelector('.menu')).display === 'none', dirty: hist.i !== hist.saved, status: $('status').textContent })"""

        class Item:  # simulates a menu click
            def __init__(self, act):
                self.act = act

            def representedObject(self):
                return self.act

        answer = "setTimeout(() => {{ $('mInput').value = {0}; $('mOk').click(); }}, 300); 1"
        seq = [("initial", None), ("menu random", "random"), ("menu undo", "undo"), ("menu redo", "redo"),
               ("menu randomSeed + answer 4321", ("randomSeed", answer.format('"4321"'))),
               ("menu rename + answer", ("rename", answer.format('"Selftest name"'))),
               ("menu duplicate", "selectFirst"), ("menu undo 2", "undo"),
               ("dirty after edit", None)]

        def step(i):
            if i >= len(seq):
                return finish()
            label, act = seq[i]
            if act == "selectFirst":
                self.js("select(doc.mods.find(m => m.type !== 'HEADM' && m.type !== 'TAIL' && !/KNOB|MENUPAGE|TEXTBLOCK/.test(m.type))); 1")
                self.menuAction_(Item("duplicate"))
            elif isinstance(act, tuple):
                self.menuAction_(Item(act[0]))
                self.js(act[1])
            elif act:
                self.menuAction_(Item(act))

            def got(r, e):
                steps.append([label, json.loads(r) if r else str(e)])
                step(i + 1)

            def after():
                self.js(probe, got)
            AppHelper.callLater(1.0, after)
        step(0)


def main():
    setup_log()
    serial_port = None
    if "--port" in sys.argv:
        serial_port = sys.argv[sys.argv.index("--port") + 1]
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    ctrl = Controller.alloc().init()
    ctrl.srv, ctrl.bridge, url = start_gateway(serial_port)
    gw.DIALOGS["save"] = ctrl.ask_save
    gw.DIALOGS["open"] = ctrl.ask_open
    gw.DIALOGS["open_dbase"] = ctrl.ask_open_dbase
    gw.HOOKS["quit"] = lambda: AppHelper.callAfter(APP().terminate_, None)
    app.setDelegate_(ctrl)
    ctrl.build_menus()
    ctrl.build(url)
    app.activateIgnoringOtherApps_(True)
    AppHelper.runEventLoop()


if __name__ == "__main__":
    main()
