# CI stub replacing beacon.py for motion tests: real Beacon needs a live sample stream batch mode cannot give.
class BeaconStub:
    def __init__(self, config):
        self.printer = config.get_printer()
        for opt in config.get_prefix_options(""):
            config.get(opt)
        self.offsets = (config.getfloat("x_offset", 0.0), config.getfloat("y_offset", 0.0), 0.0)
        self.params = {
            "probe_speed": config.getfloat("speed", 5.0),
            "lift_speed": config.getfloat("lift_speed", 5.0),
            "samples": 1,
            "sample_retract_dist": 2.0,
            "samples_tolerance": 0.1,
            "samples_tolerance_retries": 0,
            "samples_result": "average",
        }
        self.results = []
        self.ppins = self.printer.lookup_object("pins")
        self.ppins.register_chip("probe", self)
        # Without a 'probe' object z_tilt and bed_mesh fall back to a manual probe that waits forever.
        self.printer.add_object("probe", self)
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

    # Probe interface (klippy/extras/probe.py): every point reads a flat bed at z=0.
    def get_probe_params(self, gcmd=None):
        return dict(self.params)

    def get_offsets(self):
        return self.offsets

    def get_status(self, eventtime):
        return {"name": "beacon", "last_query": False, "last_z_result": 0.0}

    def start_probe_session(self, gcmd):
        self.results = []
        return self

    def run_probe(self, gcmd):
        pos = self.printer.lookup_object("toolhead").get_position()
        self.results.append([pos[0], pos[1], 0.0])

    def pull_probed_results(self):
        res, self.results = self.results, []
        return res

    def end_probe_session(self):
        self.results = []


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
