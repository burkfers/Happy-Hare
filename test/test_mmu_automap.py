# Happy Hare - automap candidate resolution tests.
#
# The fake Klipper runs the real MMU_SLICER_TOOL_MAP command. Spool weight is
# assigned directly here because it is transient Moonraker metadata rather than a
# user-facing MMU_GATE_MAP option; test_mmu_moonraker covers its wire path.

import unittest

from test.hh import session


class TestAutomapResolution(unittest.TestCase):

    def setUp(self):
        self.hh = session('boxturtle')
        self.hh.boot()
        self.assertEqual(self.hh.errors, [])

    def tearDown(self):
        self.hh.close()

    def _set_gate(self, gate, material='PLA', color='ff0000', name='PLA Basic',
                  spool_id=None, remaining=1000, initial=1000):
        spool_id = gate + 1 if spool_id is None else spool_id
        gate_map = {
            gate: {
                'spool_id': spool_id,
                'material': material,
                'color': color,
                'name': name,
                'temp': 200,
                'remaining_weight': remaining,
                'initial_weight': initial,
            }
        }
        self.hh.run_gcode(
            'MMU_GATE_MAP MAP="%s" FROM_SPOOLMAN=1 QUIET=1' % repr(gate_map))

    def _reset_tools(self):
        self.hh.run_gcode('MMU_TTG_MAP RESET=1 QUIET=1')
        self.hh.run_gcode('MMU_SLICER_TOOL_MAP RESET=1 QUIET=1')

    def _automap(self, strategy, material='PLA', color='ff0000', name='PLA Basic',
                 resolution='least_full'):
        self.hh.run_gcode(
            'MMU_SLICER_TOOL_MAP TOOL=0 MATERIAL=%s COLOR=%s NAME="%s" '
            'AUTOMAP=%s RESOLUTION=%s QUIET=1'
            % (material, color, name, strategy, resolution))

    def _assert_gate(self, gate):
        self.assertEqual(self.hh.mmu.gate_maps.ttg_map[0], gate)

    def test_least_full_is_independent_of_gate_order(self):
        self._set_gate(0, remaining=300, initial=1000)
        self._set_gate(1, remaining=100, initial=500)
        self._set_gate(2, remaining=900, initial=1000)
        self._set_gate(3, material='PETG', spool_id=4)
        self._reset_tools()
        self._automap('material')
        self._assert_gate(1)

    def test_least_full_applies_to_name_material_and_exact_color(self):
        cases = (
            ('filament_name', 'PLA Basic', 'PLA', 'ff0000'),
            ('material', 'PLA', 'PLA', 'ff0000'),
            ('color', 'PLA Basic', 'PLA', 'ff0000'),
        )
        for strategy, name, material, color in cases:
            with self.subTest(strategy=strategy):
                self._set_gate(0, material=material, color=color, name=name,
                               remaining=300, initial=1000)
                self._set_gate(1, material=material, color=color, name=name,
                               remaining=100, initial=500)
                self._set_gate(2, material='PETG', color='00ff00', name='PETG Basic',
                               spool_id=4, remaining=10, initial=1000)
                self._reset_tools()
                self._automap(strategy, material=material, color=color, name=name)
                self._assert_gate(1)

    def test_least_full_only_breaks_closest_color_ties(self):
        self._set_gate(0, color='ff0000', remaining=300, initial=1000)
        self._set_gate(1, color='ff0000', remaining=100, initial=500)
        self._set_gate(2, color='00ff00', remaining=10, initial=1000)
        self._reset_tools()
        self._automap('closest_color')
        self._assert_gate(1)

    def test_first_and_last_select_gate_order(self):
        for gate in range(4):
            self._set_gate(gate, spool_id=gate + 1)

        self._reset_tools()
        self._automap('material', resolution='first')
        self._assert_gate(0)

        self._reset_tools()
        self._automap('material', resolution='last')
        self._assert_gate(3)

    def test_least_full_falls_back_when_spoolman_data_is_missing(self):
        for gate in range(3):
            self._set_gate(gate, spool_id=gate + 1)
            self.hh.mmu.gate_maps.gate_remaining_weight[gate] = None
            self.hh.mmu.gate_maps.gate_initial_weight[gate] = None
        self._reset_tools()
        self._automap('material')
        self._assert_gate(2)
        self.assertIn('fullness unavailable', ' '.join(self.hh.console).lower())


if __name__ == '__main__':
    unittest.main()
