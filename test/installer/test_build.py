# Happy Hare installer refresh integration tests.
#
# A same-version refresh is the baseline for every future upgrade: before a migration can
# transform renamed or moved settings, the installer must be able to rebuild the current
# templates without losing existing user values.  This test drives build_config_file(), not
# a test double, against the real BoxTurtle Kconfig profile, all four rendered base files and
# the LED theme file. The 4.00 fixture predates the theme move and still carries the effect_*
# assignments in the hardware file; the refresh must migrate them, user edits included.
#
# The fixture is deliberately a compact installed-config fragment rather than a frozen copy
# of every generated line.  It records only user-owned state.  Everything else must come from
# today's real templates, which prevents a second stale template tree growing under test/.
# Outputs are written to temporary directories; fixture files are never modified.
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import glob
import os
import re
import tempfile
import unittest

from installer.parser import ConfigBuilder
from test.hh import cfg, profiles

# 'effect_name, (r, g, b)[, duration]' with the refresh's value-column re-alignment ignored.
EFFECT_RE = re.compile(r"^\s*([\w_]+),\s*\(([^)]*)\)(?:,\s*([0-9.]+))?\s*$")


def effect_value(parser, section, option):
    match = EFFECT_RE.match(parser.get(section, option))
    assert match is not None, "unparseable effect value: %r" % parser.get(section, option)
    color = tuple(float(x) for x in match.group(2).split(","))
    duration = float(match.group(3)) if match.group(3) else None
    return match.group(1), color, duration


class TestV400Refresh(unittest.TestCase):
    """Refresh an installed v4.00 configuration to v4.00 twice."""

    FIXTURE = os.path.join(os.path.dirname(__file__), "refresh", "4_00", "input")
    INSTALLED_NAMES = {
        "config/base/mmu.cfg": "mmu/base/mmu.cfg",
        "config/base/mmu_hardware.cfg": "mmu/base/mmu_hardware_unit0.cfg",
        "config/base/mmu_macro_vars.cfg": "mmu/base/mmu_macro_vars.cfg",
        "config/base/mmu_parameters.cfg": "mmu/base/mmu_parameters_unit0.cfg",
        "config/led_theme/mmu_leds.cfg": "mmu/led_theme/mmu_leds_unit0.cfg",
    }

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        cls.first = os.path.join(cls.tmpdir.name, "first")
        cls.second = os.path.join(cls.tmpdir.name, "second")

        profile = profiles.get("boxturtle")
        env = dict(cfg._SINGLE_UNIT_ENV, F_CFG_UPGRADE_MODE="refresh")
        with cfg._env(env):
            kconfig = cfg._kconfig("installer-refresh-4.00", profile.syms)
            cls._build_pass(kconfig, cls.fixture_files(), cls.first)
            cls._build_pass(kconfig, cls.output_files(cls.first), cls.second)

    @classmethod
    def tearDownClass(cls):
        cls.tmpdir.cleanup()

    @classmethod
    def fixture_files(cls):
        return sorted(glob.glob(os.path.join(cls.FIXTURE, "*.cfg")))

    @classmethod
    def output_files(cls, root):
        return sorted(
            glob.glob(os.path.join(root, "mmu", "base", "*.cfg"))
            + glob.glob(os.path.join(root, "mmu", "led_theme", "*.cfg"))
        )

    @classmethod
    def _build_pass(cls, kconfig, input_files, out_root):
        from installer import build

        extra = {"PARAM_TOTAL_NUM_GATES": kconfig.getint("PARAM_NUM_GATES")}
        env = dict(cfg._SINGLE_UNIT_ENV,
                   OUT=out_root,
                   F_CFG_UPGRADE_MODE="refresh")
        with cfg._env(env), cfg._chdir(cfg.REPO_ROOT):
            for template, installed_name in cls.INSTALLED_NAMES.items():
                dest = os.path.join(out_root, installed_name)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                build.build_config_file(
                    template,
                    dest,
                    kconfig,
                    input_files,
                    extra,
                )

    @classmethod
    def parsed(cls, root, name):
        return ConfigBuilder(os.path.join(root, name))

    def test_existing_user_values_survive_refresh(self):
        mmu = self.parsed(self.first, "mmu/base/mmu.cfg")
        self.assertEqual(mmu.get("mmu_machine", "happy_hare_version"), "4.0.0")
        self.assertEqual(mmu.get("mmu_parameters", "log_level"), "4")

        macro_vars = self.parsed(self.first, "mmu/base/mmu_macro_vars.cfg")
        self.assertEqual(
            macro_vars.get(
                "gcode_macro _MMU_SEQUENCE_VARS",
                "variable_user_pre_load_extension",
            ),
            '"CUSTOM_PRE_LOAD"',
        )

        parameters = self.parsed(self.first, "mmu/base/mmu_parameters_unit0.cfg")
        section = "mmu_unit_parameters unit0"
        self.assertEqual(parameters.get(section, "gear_load_speed"), "123")
        self.assertEqual(parameters.get(section, "gear_buzz_accel"), "987")

    def test_user_defined_excluded_config_survives_refresh(self):
        mmu = self.parsed(self.first, "mmu/base/mmu.cfg")
        self.assertTrue(mmu.has_section("gcode_macro USER_REFRESH_SENTINEL"))
        self.assertEqual(
            mmu.get("gcode_macro USER_REFRESH_SENTINEL", "gcode"),
            "M118 refresh fixture survived",
        )

        hardware = self.parsed(self.first, "mmu/base/mmu_hardware_unit0.cfg")
        self.assertTrue(hardware.has_section("temperature_sensor fixture_chamber"))
        self.assertEqual(
            hardware.get("temperature_sensor fixture_chamber", "sensor_pin"),
            "unit0:PA0",
        )

    def test_second_refresh_is_byte_identical(self):
        first = self.output_files(self.first)
        second = self.output_files(self.second)
        self.assertEqual([os.path.basename(path) for path in first],
                         [os.path.basename(path) for path in second])
        for left, right in zip(first, second):
            with self.subTest(file=os.path.basename(left)):
                with open(left, "rb") as f:
                    first_bytes = f.read()
                with open(right, "rb") as f:
                    second_bytes = f.read()
                self.assertEqual(first_bytes, second_bytes)

    def test_edited_effect_values_migrate_to_the_led_theme(self):
        """The 4.00 fixture still carries effect_* in the hardware file (the
        pre-theme layout). A refresh moves them to the theme file, so a user's
        edits must arrive there, and the hardware file must no longer carry
        effect options at all (the theme is included ahead of it, so any that
        stayed would shadow the theme)."""
        theme = self.parsed(self.first, "mmu/led_theme/mmu_leds_unit0.cfg")
        section = "mmu_leds unit0"
        self.assertEqual(effect_value(theme, section, "effect_error"),
                         ("mmu_sparkle", (1.0, 0.0, 0.0), 3.0))
        self.assertEqual(effect_value(theme, section, "effect_heating"),
                         ("mmu_breathing_blue_slow", (0.5, 0.2, 0.0), None))
        # Unedited (stock) values arrive too, matching the template.
        self.assertEqual(effect_value(theme, section, "effect_initialized"),
                         ("mmu_rainbow", (0.5, 0.2, 0.0), 8.0))

        hardware = self.parsed(self.first, "mmu/base/mmu_hardware_unit0.cfg")
        for option in ("effect_error", "effect_heating", "effect_initialized"):
            self.assertFalse(hardware.has_option(section, option), option)
        # The hardware file points at the theme with Klipper's include syntax, the
        # path relative to the hardware file's own directory.
        self.assertIn("include ../led_theme/mmu_leds_unit0.cfg", hardware.sections())

    def test_migrated_effect_values_survive_the_second_refresh(self):
        theme = self.parsed(self.second, "mmu/led_theme/mmu_leds_unit0.cfg")
        self.assertEqual(effect_value(theme, "mmu_leds unit0", "effect_error"),
                         ("mmu_sparkle", (1.0, 0.0, 0.0), 3.0))
        self.assertEqual(effect_value(theme, "mmu_leds unit0", "effect_heating"),
                         ("mmu_breathing_blue_slow", (0.5, 0.2, 0.0), None))


if __name__ == "__main__":
    unittest.main()
