# CI-only Klipper extra for batch-mode runs of the RF50 config; never install it on a printer.
#
# Strict unknown commands and the assert helper follow Kalico's test/klippy_testing_plugin.py
# (https://github.com/KalicoCrew/kalico), adapted to this fork's gcode.py.
import logging
import os

from . import aht10


def _strict_unknown(orig_default):
    """Wrap gcode.cmd_default so 'Unknown command' raises instead of only logging (batch exit 0 otherwise)."""

    def handler(gcmd):
        orig_respond = gcmd.respond_info

        def respond_info(msg, log=True):
            if msg.startswith("Unknown command:"):
                raise gcmd.error(msg)
            orig_respond(msg, log)

        gcmd.respond_info = respond_info
        return orig_default(gcmd)

    return handler


def _assert_commands(gcode):
    """CI_ASSERT_COMMANDS CMDS=A,B,PREFIX_*: fail unless each name (or prefix) is registered; runs nothing."""

    def handler(gcmd):
        names = [n.strip().upper() for n in gcmd.get("CMDS").split(",") if n.strip()]
        have = gcode.ready_gcode_handlers
        missing = [
            n for n in names
            if not (any(c.startswith(n[:-1]) for c in have) if n.endswith("*") else n in have)
        ]
        if missing:
            raise gcmd.error("CI: commands not defined: %s" % ", ".join(missing))
        gcmd.respond_info("CI: %d commands defined" % len(names))

    return handler


def _quiet_real_beacon():
    """Real beacon.py: skip connect-time NVM reads and the sample watchdog (batch mode never answers queries)."""
    try:
        from . import beacon
    except ImportError:
        return
    if not hasattr(beacon, "BeaconMCUTempHelper"):
        return  # CI stub beacon.py is installed
    beacon.BeaconMCUTempHelper.build_with_nvm = classmethod(lambda *_: None)
    beacon.BeaconTempModelBuilder.build_with_nvm = lambda *_: None
    beacon.BeaconProbe._stream_timeout = lambda self, *_: self.reactor.NEVER
    logging.info("ci_batch_shims: real beacon.py, NVM + stream watchdog disabled")


def load_config(config):
    aht10.AHTBase.handle_connect = lambda *_: None  # I2C handshake needs an MCU reply
    _quiet_real_beacon()
    start_args = config.get_printer().get_start_args()
    if start_args.get("log_file"):  # HH puts mmu.log beside it; test_klippy passes a relative -l
        start_args["log_file"] = os.path.abspath(start_args["log_file"])
    gcode = config.get_printer().lookup_object("gcode")
    gcode.cmd_default = _strict_unknown(gcode.cmd_default)
    gcode.register_command("CI_ASSERT_COMMANDS", _assert_commands(gcode))
    return object()
