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
    """CI_ASSERT_COMMANDS CMDS=A,B: fail unless each exact name is registered; runs nothing."""

    def handler(gcmd):
        names = [n.strip().upper() for n in gcmd.get("CMDS").split(",") if n.strip()]
        if not names:
            raise gcmd.error("CI: CI_ASSERT_COMMANDS got an empty CMDS list")
        have = gcode.ready_gcode_handlers
        # Exact names only: a prefix match let AXIS_MAINTENANCE_FINISH_X stand in for a missing AXIS_MAINTENANCE_Y.
        missing = [n for n in names if n not in have]
        if missing:
            raise gcmd.error("CI: commands not defined: %s" % ", ".join(missing))
        gcmd.respond_info("CI: %d commands defined" % len(names))

    return handler


def _set_filament(printer):
    """CI_SET_FILAMENT PRESENT=0|1: set every filament switch sensor (batch mode never reports pin states)."""

    def handler(gcmd):
        present = bool(gcmd.get_int("PRESENT", 1, minval=0, maxval=1))
        now = printer.get_reactor().monotonic()
        sensors = printer.lookup_objects("filament_switch_sensor")
        if not sensors:
            raise gcmd.error("CI: no filament_switch_sensor objects")
        for _, sensor in sensors:
            sensor.runout_helper.note_filament_present(now, present)
        gcmd.respond_info("CI: %d filament sensors present=%d" % (len(sensors), present))

    return handler


def _mmu_print_sync(printer):
    """CI_MMU_PRINT_SYNC ENABLE=0|1: set HH's in-print gear sync; MMU_TEST_CONFIG cannot, always_gripped forces 1."""

    def handler(gcmd):
        mmu = printer.lookup_object("mmu", None)
        if mmu is None:
            raise gcmd.error("CI: no [mmu] object")
        mmu.sync_to_extruder = gcmd.get_int("ENABLE", minval=0, maxval=1)
        gcmd.respond_info("CI: mmu sync_to_extruder=%d" % mmu.sync_to_extruder)

    return handler


def _hold_exit_for_sd_print(printer, gcode):
    """Batch EOF exits at once, cutting an SD print short: hold 'exit' until it ends, fail unless complete."""
    orig = gcode.request_restart
    reactor = printer.get_reactor()

    def request_restart(result):
        sd = printer.lookup_object("virtual_sdcard", None)
        stats = printer.lookup_object("print_stats", None)
        if result != "exit" or sd is None or stats is None:
            return orig(result)
        reactor.register_timer(lambda et: check(et, sd, stats), reactor.NOW)

    def check(eventtime, sd, stats):
        if sd.is_active():
            return eventtime + 0.1
        status = stats.get_status(eventtime)
        if status["state"] in ("standby", "complete"):
            if status["state"] == "complete":
                logging.info("CI: SD print complete: %s", status["filename"])
            orig("exit")
        else:
            logging.error("CI: SD print %s ended %s: %s", status["filename"], status["state"], status["message"])
            orig("error_exit")
        return reactor.NEVER

    gcode.request_restart = request_restart


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
    gcode.register_command("CI_SET_FILAMENT", _set_filament(config.get_printer()))
    gcode.register_command("CI_MMU_PRINT_SYNC", _mmu_print_sync(config.get_printer()))
    _hold_exit_for_sd_print(config.get_printer(), gcode)
    return object()
