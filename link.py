"""Finding the band. A first double-tap is easy to miss, so this keeps trying for a few
minutes, and after every miss it looks around and says, in plain words, what it saw.
"""
import time

from vexo_open.sync import Band, VexoError

PREFIX = "Vexo-HACK-"


def usb_bands():
    """Serial ports that look like a Vexo band on the USB cable ([] if none, or no pyserial)."""
    try:
        from vexo_open.transports.serial import SerialTransport
        return SerialTransport.find_ports()
    except Exception:
        return []


def look_around(seconds=5.0):
    """(how many Bluetooth devices this computer can see, the Vexo band names among them, problem)."""
    try:
        import asyncio
        from bleak import BleakScanner

        async def scan():
            return await BleakScanner.discover(timeout=seconds, return_adv=True)

        found = asyncio.run(scan())
    except Exception as problem:
        return 0, [], str(problem)
    names = set()
    for device, advert in found.values():
        name = getattr(advert, "local_name", None) or getattr(device, "name", None) or ""
        if name.startswith(PREFIX):
            names.add(name)
    return len(found), sorted(names), ""


def explain(wanted, seen, names, problem):
    """What the look-around means, for the person holding the band."""
    if problem:
        return ("蓝牙扫描出错：%s\n"
                "  请检查：系统设置 → 隐私与安全性 → 蓝牙，把「终端 / Terminal」打开，然后重新双击 start.command。" % problem)
    if seen == 0:
        return ("这台电脑一个蓝牙设备都没扫到。\n"
                "  ① 屏幕右上角控制中心里，蓝牙是不是开着？\n"
                "  ② 系统设置 → 隐私与安全性 → 蓝牙，是否允许了「终端 / Terminal」？改完后重新双击 start.command。")
    if wanted in names:
        return "看到 %s 了，但没连上。再敲两下手环，马上重试。" % wanted
    if names:
        return ("附近正在广播的手环有：%s，但没有 %s。\n"
                "  请再看一眼袋子上的编号。如果编号不同，改 config.json 里的 band_number。" % (", ".join(names), wanted))
    return ("扫到了 %d 个蓝牙设备，但没有任何 Vexo 手环在广播。可能的原因：\n"
            "  ① 手环没电或没开机：用 USB-C 线把手环接到这台电脑上（接上就有电，程序还能直接走 USB 连接）。\n"
            "  ② 没敲成功：用指尖在手环的小方块上快速敲两下，灯闪蓝光才算成功，闪光只持续 60 秒。\n"
            "  ③ 手环正被别的程序占着：关掉 Vexo 的 dashboard 网页，或让队友断开。" % seen)


def connect(number, transport="ble", minutes=4, say=print):
    """Returns (band, kind). Tries the USB cable first if a band is plugged in, then
    Bluetooth again and again until `minutes` are over."""
    wanted = "%s%02d" % (PREFIX, number)
    if transport == "ble" and usb_bands():
        say("发现手环插在 USB 线上：直接走 USB 连接（比蓝牙稳）。")
        transport = "serial"
    if transport == "serial":
        try:
            band = Band.connect(None, transport="serial", auto_reconnect=True)
        except VexoError as problem:
            say("USB 连接没成功（%s），改用蓝牙。" % problem.message)
        else:
            if band.number != number:
                say("注意：这只手环自己报的编号是 %s，不是 %s。先按它实际的编号用。" % (band.number, number))
            return band, "serial"
    end = time.time() + minutes * 60
    attempt = 0
    while True:
        attempt += 1
        say("")
        say("[第 %d 次] 正在找 %s … 现在用指尖在手环上快速敲两下，灯会闪蓝光。" % (attempt, wanted))
        try:
            return Band.connect(number, transport="ble", auto_reconnect=True, scan_seconds=15), "ble"
        except VexoError as problem:
            if problem.code != "not-found-nearby" or time.time() > end:
                raise
        if usb_bands():                              # plugged in meanwhile
            say("手环刚接上 USB：改走 USB。")
            try:
                band = Band.connect(None, transport="serial", auto_reconnect=True)
                if band.number != number:
                    say("注意：这只手环自己报的编号是 %s，不是 %s。" % (band.number, number))
                return band, "serial"
            except VexoError as problem:
                say("USB 连接没成功（%s）。" % problem.message)
        seen, names, problem = look_around()
        say("没找到。" + explain(wanted, seen, names, problem))
