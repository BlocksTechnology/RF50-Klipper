# CI stub replacing beacon.py for motion tests: real Beacon needs a live sample stream batch mode cannot give.
class BeaconStub:
    def __init__(self, config):
        self.printer = config.get_printer()
        for opt in config.get_prefix_options(""):
            config.get(opt)
        self.ppins = self.printer.lookup_object("pins")
        self.ppins.register_chip("probe", self)
        self.endstop_pin = "Toolhead:PB9"
        gcode = self.printer.lookup_object("gcode")
        for cmd in ("BEACON_AUTO_CALIBRATE", "BEACON_CALIBRATE", "BEACON_QUERY",
                    "BEACON_OFFSET_COMPARE", "BEACON_POKE", "BEACON_MODEL_SELECT"):
            gcode.register_command(cmd, self.cmd_noop, desc="CI stub")

    def setup_pin(self, pin_type, pin_params):
        if pin_type != "endstop" or pin_params["pin"] != "z_virtual_endstop":
            raise self.ppins.error("beacon stub: only probe:z_virtual_endstop")
        return _VirtualEndstop(self.ppins.setup_pin("endstop", self.endstop_pin))

    def cmd_noop(self, gcmd):
        gcmd.respond_info("beacon stub: %s ignored" % gcmd.get_command())


class _VirtualEndstop:
    """Delegates to a real MCU endstop and reports z=0 like a probe virtual endstop."""

    def __init__(self, mcu_endstop):
        self._e = mcu_endstop

    def __getattr__(self, name):
        return getattr(self._e, name)

    def get_position_endstop(self):
        return 0.0


def load_config(config):
    return BeaconStub(config)
