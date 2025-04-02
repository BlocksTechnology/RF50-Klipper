import typing
from functools import partial


class UnloadFilamentError(Exception):
    """Raised when there is an error unloading filament"""

    def __init__(self, message, errors: typing.Optional[str]):
        super(UnloadFilamentError, self).__init__(message)
        self.errors = errors


class UnloadFilament:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.gcode = self.printer.lookup_object("gcode")

        self.custom_boundary_object = None
        self.min_event_systime = None
        self.toolhead = None
        self.bucket_object = None
        self.cutter_object = None
        self.filament_flow_sensor_object = self.filament_flow_sensor_name = None
        self.filament_switch_sensor_object = self.filament_switch_sensor_name = None
        self.unload_started = None
        self.unextrude_count: int = 0
        self.travel_speed = None

        # * Register Event handlers
        self.printer.register_event_handler("klippy:connect", self.handle_connect)
        self.printer.register_event_handler("klippy:ready", self.handle_ready)

        # * Module Configs
        self.idex = config.getboolean("idex", False)
        self.has_custom_boundary = config.getboolean("has_custom_boundary", False)
        self.travel_speed = config.getfloat(
            "travel_speed", 100.0, minval=50.0, maxval=500.0
        )
        self.bucket = config.getboolean("bucket", False)

        if not self.bucket:
            self.filament_flow_sensor_name = config.get(
                "filament_flow_sensor_name", None
            )

        self.filament_switch_sensor_name = config.get(
            "filament_switch_sensor_name", None
        )

        self.park = config.getfloatlist("park_xy", None, count=2)

        self.unload_speed = config.getfloat(
            "unload_speed", default=50.0, minval=10.0, maxval=100.0
        )

        self.cutter_name = config.get("cutter_sensor_name", None)

        self.timeout = config.getint("timeout", default=None, minval=10, maxval=1000)

        # * Callback Timers
        self.unextrude_timer = self.reactor.register_timer(
            self.unextrude, self.reactor.NEVER
        )
        self.verify_flow_sensor_timer = self.reactor.register_timer(
            self.verify_flow_sensor_state, self.reactor.NEVER
        )
        self.verify_switch_sensor_timer = self.reactor.register_timer(
            self.verify_switch_sensor_state, self.reactor.NEVER
        )

        self.gcode.register_command(
            "UNLOAD_FILAMENT",
            self.cmd_UNLOAD_FILAMENT,
            "GCODE Macro to unload filament, takes into account if there is a belay and or a filament cutter with a sensor",
        )

    def handle_connect(self):
        self.toolhead = self.printer.lookup_object("toolhead")

    def handle_ready(self):
        self.min_event_systime = self.reactor.monotonic() + 2.0

        if self.has_custom_boundary:
            self.custom_boundary_object = self.printer.lookup_object("bed_custom_bound")

        if self.bucket:
            self.bucket_object = self.printer.lookup_object("bucket")

        if self.cutter_name is not None:
            if (
                self.printer.lookup_object(f"cutter_sensor {self.cutter_name}", None)
                is not None
            ):
                self.cutter_object = self.printer.lookup_object(
                    f"cutter_sensor {self.cutter_name}", None
                )

                self.printer.register_event_handler(
                    "cutter_sensor:no_filament",
                    self.handle_cutter_fnp,
                )

        if self.idex:
            self.idex_object = self.printer.lookup_object("dual_carriage")

        if self.filament_flow_sensor_name is not None:
            self.filament_flow_sensor_object = self.printer.lookup_object(
                f"filament_motion_sensor {self.filament_flow_sensor_name}", None
            )

        if self.filament_switch_sensor_name is not None:
            self.filament_switch_sensor_object = self.printer.lookup_object(
                f"filament_switch_sensor {self.filament_switch_sensor_name}", None
            )

    def handle_cutter_fnp(self):
        """React to cutter sensor no filament state"""
        if self.unload_started:
            self.gcode.respond_info("Pulling filament out of the printer wait....")
            self.reactor.update_timer(self.unextrude_timer, self.reactor.NOW)

    def verify_switch_sensor_state(self, eventtime):
        """Routine to verify if the filament is actually unloaded or not
        The switch sensor here is assumed to be at the end of the filament pathway.
        """
        if not self.unload_started:
            return self.reactor.NEVER

        if self.filament_switch_sensor_object.get_status(eventtime)[
            "filament_detected"
        ]:
            return eventtime + 1.250
        else:
            self.reactor.update_timer(self.unextrude_timer, self.reactor.NEVER)
            self.reactor.register_callback(self.unload_end)
            return self.reactor.NEVER

    def verify_flow_sensor_state(
        self, eventtime
    ):  # TODO Right now it does nothing, Reacto the filament presence if its needed else DELETE IT
        """Verify the presence of filament on the flow sensor and react to it."""
        if not self.unload_started:
            return self.reactor.NEVER

        if self.filament_flow_sensor_object is None:
            return self.reactor.NEVER

        if self.filament_flow_sensor_object.runout_helper.get_status(eventtime)[
            "filament_detected"
        ]:
            return eventtime + 1.0

        return eventtime + 1.250

    def unload_end(self, eventtime=None):
        if not self.unload_started:
            return False

        self.unload_started = False
        self.printer.send_event("unload_filament:end")
        self.toolhead.wait_moves()

        self.gcode.run_script_from_command("G91\nM400")
        self.gcode.run_script_from_command("M83\nM400")
        self.gcode.run_script_from_command(
            "G92 E0.0\nM400"
        )  # Restore extruder position
        self.gcode.run_script_from_command("M82\nM400")

        self.toolhead.wait_moves()
        self.gcode.respond_info("Cooling down extruder")
        
        self.restore_state()

        if self.custom_boundary_object is not None:
            self.custom_boundary_object.set_custom_boundary()

        self.heat_and_wait(0, wait=False)

        if self.idex:
            self.gcode.respond_info("Parking toolhead 0")
            self.gcode.run_script_from_command("T0 PARK\nM400")
        self.toolhead.wait_moves()

        self.gcode.respond_info("[UNLOAD FILAMENT] Finished.")
        return True

    def unextrude(self, eventtime):
        """Move the extruder to unload"""
        if not self.unload_started:
            return self.reactor.NEVER

        try:
            if self.timeout is not None:
                if self.unextrude_count > self.timeout:
                    self.reactor.update_timer(
                        self.verify_switch_sensor_timer, self.reactor.NEVER
                    )
                    completion = self.reactor.register_callback(self.unload_end)
                    completion.wait()
                    return self.reactor.NEVER
                self.unextrude_count += 1
            self.move_extruder_mm(distance=-10, speed=self.unload_speed, wait=False)
            return eventtime + float((10 / (self.unload_speed)))

        except Exception as e:
            raise UnloadFilamentError(
                f"[UNLOAD FILAMENT] Error while unloading: {e}", errors=e
            )

    def disable_sensors(self):
        if self.filament_flow_sensor_object is not None:
            self.filament_flow_sensor_object.runout_helper.sensor_enabled = 0

        if self.filament_switch_sensor_object is not None:
            self.filament_switch_sensor_object.runout_helper.sensor_enabled = 0
            self.gcode.respond_info("filament switch sensor is not enabled")

        return True

    def enable_sensors(self):
        if self.filament_flow_sensor_object is not None:
            self.filament_flow_sensor_object.runout_helper.sensor_enabled = 1

        if self.filament_switch_sensor_object is not None:
            self.gcode.respond_info("filament switch sensor is now enabled")
            self.filament_switch_sensor_object.runout_helper.sensor_enabled = 1

        return True

    def move_extruder_mm(self, distance=10.0, speed=30.0, wait=True):
        """Move the extruder

        Args:
            distance (float): The distance in mm to move the extruder.
        """
        if self.toolhead is None:
            return
        try:
            eventtime = self.reactor.monotonic()
            gcode_move = self.printer.lookup_object("gcode_move")
            prev_pos = self.toolhead.get_position()
            gcode_move.absolute_coord = False  # G91
            v = distance * gcode_move.get_status(eventtime)["extrude_factor"]
            new_distance = v + prev_pos[3]
            self.toolhead.manual_move(
                [prev_pos[0], prev_pos[1], prev_pos[2], new_distance], speed * 60
            )
            if wait:
                self.toolhead.wait_moves()
        except Exception as e:
            raise UnloadFilamentError(f"[UNLOAD FILAMENT] Error moving extruder {e}")
        return True

    def home_needed(self):
        if self.toolhead is None:
            return
        try:
            eventtime = self.reactor.monotonic()
            kin = self.toolhead.get_kinematics()
            _homed_axes = kin.get_status(eventtime)["homed_axes"]
            if "xyz" in _homed_axes.lower():
                return
            else:
                self.gcode.run_script_from_command("G28")
        except Exception as e:
            raise UnloadFilamentError(f"[UNLOAD FILAMENT] Error homing {e}")

    def heat_and_wait(self, temp, wait: typing.Optional["bool"] = False):
        """Heats the extruder and wait.

        Method returns when  temperature is [temp - 5 ; temp + 5].
        Args:
            temp (float):
                Target temperature in Celsius.
            wait (bool, optional):
                Weather to wait or not for the temperature to reach the interval . Defaults to True
        """
        # eventtime = self.reactor.monotonic()
        extruder = self.toolhead.get_extruder()
        pheaters = self.printer.lookup_object("heaters")
        pheaters.set_temperature(extruder.get_heater(), temp, wait)
        # extruder_heater = extruder.get_heater()
        # while not self.printer.is_shutdown() and wait:
        #     self.gcode.respond_info(
        #         "[UNLOAD FILAMENT] Waiting for temperature to stabilize."
        #     )
        #     heater_temp, target = extruder_heater.get_temp(eventtime)
        #     if heater_temp >= (temp - 5) and heater_temp <= (temp + 5):
        #         return
        #     eventtime = self.reactor.pause(eventtime + 1.0)

    def increase_extrude_dist(self) -> float:
        """
        # DEPRECATED
        Increase current extruder config `max_extrude_only_distance` to the configured `minimum_extrude_dist`.

        Returns:
            float: The old `max_extrude_only_distance` as set on `[extruder]` config.
        """
        extruder = self.toolhead.get_extruder()
        _old_extruder_dist = None
        if extruder.max_e_dist < self.min_dist_to_nozzle:
            _old_extruder_dist = extruder.max_e_dist
            extruder.max_e_dist = self.min_dist_to_nozzle + 10.0
            return _old_extruder_dist
        return None

    def change_extrude_dist(self, extrude_dist):
        """
        # DEPRECATED
        Changes the `max_e_dist` variable of the current extruder object.

        Args:
            extrude_dist (float): The new value for the variable `max_e_dist` on the extruder object.
        """
        if extrude_dist is not None:
            extruder = self.toolhead.get_extruder()
            if extruder is not None:
                extruder.max_e_dist = extrude_dist

    def conditional_pause(self, eventtime):
        idle_timeout = self.printer.lookup_object("idle_timeout")
        pause_resume = self.printer.lookup_object("pause_resume")
        virtual_sdcard = self.printer.lookup_object("virtual_sdcard")

        if idle_timeout is None or pause_resume is None:
            return None

        is_printing = idle_timeout.get_status(eventtime)["state"] == "Printing"
        is_paused = pause_resume.get_status(eventtime)["is_paused"]
        has_file = virtual_sdcard.is_active()

        if is_printing and not is_paused and self.unload_started and has_file:
            if self.printer.lookup_object("gcode_macro PAUSE") is not None:
                self.gcode.run_script_from_command("PAUSE")
        return False

    def save_state(self):
        """Save gcode state and dual carriage state if the system is in IDEX configuration"""
        if self.idex:
            self.gcode.run_script_from_command(
                "SAVE_DUAL_CARRIAGE_STATE NAME=unload_carriage_state\nM400"
            )
        self.gcode.run_script_from_command("SAVE_GCODE_STATE NAME=_UNLOAD_STATE\nM400")
        return True

    def restore_state(self):
        """Restore gcode state and dual carriage state if the system is in IDEX configuration"""
        self.gcode.run_script_from_command(
            "RESTORE_GCODE_STATE NAME=_UNLOAD_STATE MOVE=1 MOVE_SPEED=100\nM400"
        )
        if self.idex:
            self.gcode.run_script_from_command(
                "RESTORE_DUAL_CARRIAGE_STATE NAME=unload_carriage_state MOVE=0\nM400"
            )
        return True

    ####################################################################################################################
    ##################################################### GCODE COMMANDS ###############################################
    ####################################################################################################################
    def cmd_UNLOAD_FILAMENT(self, gcmd):
        temp = gcmd.get("TEMPERATURE", 250.0, parser=float, minval=210.0, maxval=260.0)
        if self.toolhead is None:
            return
        try:
            if self.unload_started:
                self.gcode.respond_info("Printer already unloading filament")
                return
            self.home_needed()

            self.save_state()

            self.disable_sensors()  # So not to pause the filament switch sensor when filament is taken out
            if self.idex:
                if gcmd.get("TOOLHEAD") == "Load_T0":
                    self.gcode.run_script_from_command("T0 UNLOAD")
                else:
                    self.gcode.run_script_from_command("T1 UNLOAD")

            self.unload_started = True
            self.printer.send_event("unload_filament:start")
            self.gcode.respond_info("[UNLOAD FILAMENT] Start")

            self.gcode.run_script_from_command("G91\nM400")
            self.gcode.run_script_from_command("M83\nM400")

            # if self.custom_boundary_object is not None:
            #     self.custom_boundary_object.restore_default_boundary()

            if self.timeout is not None:
                self.unextrude_count = 0

            self.heat_and_wait(temp, wait=False)

            if self.bucket_object is not None:  # Move to the bucket position
                self.bucket_object.move_to_bucket()

            self.heat_and_wait(
                temp, wait=True
            )  # Wait for the nozzle to actually reach the temperature

            self.toolhead.wait_moves()

            if self.cutter_object is not None:
                completion = self.reactor.register_callback(
                    partial(
                        self.cutter_object.cut,
                        temp=temp,
                        return_last_pos=False,
                        off_heaters=False,
                    )
                )
                completion.wait()

            if self.cutter_object is None and self.timeout is not None:
                self.reactor.update_timer(self.unextrude_timer, self.reactor.NOW)
                if self.filament_flow_sensor_object is not None:
                    self.reactor.update_timer(
                        self.verify_flow_sensor_timer, self.reactor.NOW
                    )

            if self.filament_switch_sensor_object is not None:
                self.gcode.respond_info(
                    "[UNLOAD FILAMENT] Starting filament switch sensor unload verification in 10 seconds"
                )
                self.reactor.update_timer(
                    self.verify_switch_sensor_timer, self.reactor.NOW + 5.0
                )

        except Exception as e:
            raise UnloadFilamentError(
                f"[UNLOAD] Unexpected error while trying to unload filament: {e}"
            )

    # def get_status(self, eventtime):
    #     return {"isUnloaded": self.unload_started, "state": bool(self.state)}


def load_config(config):
    return UnloadFilament(config)
