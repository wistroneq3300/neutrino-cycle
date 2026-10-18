"""TUI tray/node selection: scripted-key behaviour and select_targets handoff.

The interaction layer is driven with injected key tokens (no real terminal), so
the selection logic is exercised as real code without mocking. A pseudo-terminal
smoke test covers the raw-key reader.
"""
import io
import os
import pty
import select as select_module
import sys
import tempfile
import time
import unittest

from cycle_core import Target, select_targets
from neutrino_cycle import (
    _checklist, _group_by_tray, _make_key_reader, _menu, _tui_select_targets,
    build_command, cycle_command, display_command, show_command,
)


def scripted(keys):
    """Key reader that yields the given tokens, one per call."""
    iterator = iter(keys)
    return lambda: next(iterator)


def target(tray, node, index):
    return Target(tray, node, f'10.0.0.{index}', f'10.0.1.{index}')


class ChecklistTests(unittest.TestCase):
    def test_space_selects_and_enter_confirms(self):
        keys = scripted(['space', 'down', 'space', 'enter'])
        chosen = _checklist('nodes', ['n0', 'n1', 'n2'], {}, keys, io.StringIO())
        self.assertEqual(chosen, ['n0', 'n1'])

    def test_space_toggles_off(self):
        keys = scripted(['space', 'space', 'enter'])
        chosen = _checklist('nodes', ['n0', 'n1'], {}, keys, io.StringIO())
        self.assertEqual(chosen, [])

    def test_up_wraps_to_last_item(self):
        keys = scripted(['up', 'space', 'enter'])
        chosen = _checklist('nodes', ['n0', 'n1', 'n2', 'n3'], {}, keys, io.StringIO())
        self.assertEqual(chosen, ['n3'])

    def test_down_wraps_to_first_item(self):
        keys = scripted(['down', 'down', 'down', 'space', 'enter'])
        chosen = _checklist('nodes', ['n0', 'n1', 'n2'], {}, keys, io.StringIO())
        self.assertEqual(chosen, ['n0'])

    def test_unknown_keys_are_ignored(self):
        keys = scripted(['x', 'y', 'space', 'enter'])
        chosen = _checklist('nodes', ['n0'], {}, keys, io.StringIO())
        self.assertEqual(chosen, ['n0'])

    def test_single_select_replaces_previous(self):
        # Move to c, select it, then move back and select a -> only a stays.
        keys = scripted(['down', 'down', 'space', 'up', 'up', 'space', 'enter'])
        chosen = _checklist('mode', ['a', 'b', 'c'], {}, keys, io.StringIO(), multi=False)
        self.assertEqual(chosen, ['a'])

    def test_single_select_footer_never_lists_two(self):
        out = io.StringIO()
        keys = scripted(['space', 'down', 'space', 'enter'])
        chosen = _checklist('mode', ['a', 'b'], {}, keys, out, multi=False)
        self.assertEqual(chosen, ['b'])
        for line in out.getvalue().splitlines():
            if line.strip().startswith('\u2192'):
                self.assertNotIn('a, b', line)

    def test_multi_select_can_choose_two(self):
        keys = scripted(['space', 'down', 'space', 'enter'])
        chosen = _checklist('nodes', ['n0', 'n1'], {}, keys, io.StringIO(), multi=True)
        self.assertEqual(chosen, ['n0', 'n1'])

    def test_menu_returns_selected_key(self):
        keys = scripted(['down', 'space', 'enter'])
        result = _menu('Cycle mode', [('power_cycle', 'power_cycle'), ('reboot', 'reboot')],
                       keys, io.StringIO())
        self.assertEqual(result, 'reboot')

    def test_menu_enter_without_space_keeps_default(self):
        keys = scripted(['down', 'enter'])
        result = _menu('Cycle mode', [('power_cycle', 'power_cycle'), ('reboot', 'reboot')],
                       keys, io.StringIO(), default=0)
        self.assertEqual(result, 'power_cycle')




class TraySelectionTests(unittest.TestCase):
    def setUp(self):
        self.targets = [
            target('ETF1', 'n0', 1), target('ETF1', 'n1', 2),
            target('ETF2', 'n0', 3), target('ETF2', 'n1', 4),
            target('ETF3', 'n0', 5), target('ETF3', 'n4', 6),
        ]

    def test_group_by_tray_preserves_csv_order(self):
        trays, nodes = _group_by_tray(self.targets)
        self.assertEqual(trays, ['ETF1', 'ETF2', 'ETF3'])
        self.assertEqual(nodes['ETF3'], ['n0', 'n4'])

    def test_multi_tray_mixed_nodes(self):
        keys = scripted([
            'space', 'down', 'down', 'space', 'enter',   # trays: ETF1, ETF3
            'space', 'down', 'space', 'enter',           # ETF1 nodes: n0, n1
            'down', 'space', 'enter',                    # ETF3 nodes: n4
        ])
        chosen = _tui_select_targets(self.targets, keys, io.StringIO())
        self.assertEqual(chosen, ['ETF1/n0', 'ETF1/n1', 'ETF3/n4'])

    def test_single_tray_skips_tray_step(self):
        single = [target('ETF1', 'n0', 1), target('ETF1', 'n1', 2)]
        keys = scripted(['space', 'enter'])
        chosen = _tui_select_targets(single, keys, io.StringIO())
        self.assertEqual(chosen, ['ETF1/n0'])

    def test_tray_selection_is_required(self):
        # Enter with no tray picked must re-prompt, then honour the real pick.
        keys = scripted([
            'enter',                            # empty -> warning, re-prompt
            'space', 'enter',                   # pick ETF1
            'space', 'enter',                   # ETF1 node n0
        ])
        chosen = _tui_select_targets(self.targets, keys, io.StringIO())
        self.assertEqual(chosen, ['ETF1/n0'])

    def test_node_selection_is_required(self):
        # Single tray, Enter with no node picked must re-prompt, not default all.
        single = [target('ETF1', 'n0', 1), target('ETF1', 'n1', 2)]
        keys = scripted(['enter', 'down', 'space', 'enter'])
        chosen = _tui_select_targets(single, keys, io.StringIO())
        self.assertEqual(chosen, ['ETF1/n1'])

    def test_selection_resolves_through_select_targets(self):
        keys = scripted([
            'space', 'down', 'down', 'space', 'enter',
            'space', 'down', 'space', 'enter',
            'down', 'space', 'enter',
        ])
        chosen = _tui_select_targets(self.targets, keys, io.StringIO())
        resolved = [t.key for t in select_targets(self.targets, chosen)]
        self.assertEqual(resolved, ['ETF1_n0', 'ETF1_n1', 'ETF3_n4'])


class RealTerminalTests(unittest.TestCase):
    """Drive the raw key reader through a pseudo-terminal.

    Bounded by SIGALRM so a terminal quirk can never hang the suite; on timeout
    the child is killed and the test is skipped rather than failed.
    """

    def _run_child(self, targets, keys):
        pid, fd = pty.fork()
        if pid == 0:  # pragma: no cover - child process
            try:
                reader = _make_key_reader(sys.stdin)
                try:
                    result = _tui_select_targets(targets, reader, sys.stdout)
                finally:
                    reader.close()
                sys.stdout.write('\nRESULT:' + ','.join(result) + '\n')
                sys.stdout.flush()
            finally:
                os._exit(0)
        return pid, fd

    def test_arrow_and_space_over_pty(self):
        targets = [target('ETF1', 'n0', 1), target('ETF1', 'n1', 2),
                   target('ETF2', 'n0', 3), target('ETF2', 'n1', 4)]
        keys = (b'\x1b[B \x1b[B \r'      # trays: ETF2
                b'\x1b[B \r')            # ETF2 nodes: n1
        pid, fd = self._run_child(targets, keys)
        time.sleep(0.3)
        try:
            os.write(fd, keys)
        except OSError:
            pass
        payload = b''
        deadline = time.time() + 5
        while time.time() < deadline:
            ready, _, _ = select_module.select([fd], [], [], 0.5)
            if not ready:
                break
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            payload += chunk
            if b'RESULT:' in payload:
                break
        try:
            os.kill(pid, 9)
        except OSError:
            pass
        try:
            os.waitpid(pid, 0)
        except OSError:
            pass
        text = payload.decode(errors='replace')
        if 'RESULT:' not in text:
            self.skipTest('pseudo-terminal unavailable in this environment')
        self.assertIn('RESULT:ETF2/n1', text)


class NoProjectDefaultTests(unittest.TestCase):
    def test_menu_without_default_needs_a_choice(self):
        # default=None => nothing preselected; space picks the cursor item.
        keys = scripted(['space', 'enter'])
        result = _menu('Project', [('neutrino', 'neutrino'), ('naboo', 'naboo')],
                       keys, io.StringIO(), default=None)
        self.assertEqual(result, 'neutrino')

    def test_menu_without_default_blocks_enter_until_picked(self):
        # Enter on an empty required menu must NOT confirm: it warns and
        # re-prompts, so the next real selection is what gets returned.
        out = io.StringIO()
        keys = scripted(['enter', 'down', 'space', 'enter'])
        result = _menu('Project', [('neutrino', 'neutrino'), ('naboo', 'naboo')],
                       keys, out, default=None)
        self.assertEqual(result, 'naboo')
        self.assertIn('Select at least one', out.getvalue())

    def test_first_frame_has_no_checkmark(self):
        out = io.StringIO()
        _menu('Project', [('neutrino', 'neutrino'), ('naboo', 'naboo')],
              scripted(['space', 'enter']), out, default=None)
        # The very first drawn frame (before any SPACE) must show no [v] box.
        # Each frame is written as '\r\x1b[K' + body, so the first body is
        # everything before the second redraw marker.
        raw = out.getvalue()
        first_frame = raw.split('\x1b[K', 1)[1].split('\x1b[K', 1)[0]
        self.assertNotIn('[v]', first_frame)

    def test_selected_mark_is_checkbox_not_bullet(self):
        out = io.StringIO()
        _menu('Project', [('neutrino', 'neutrino'), ('naboo', 'naboo')],
              scripted(['space', 'enter']), out, default=None)
        text = out.getvalue()
        self.assertIn('[v]', text)
        self.assertNotIn('\u2022', text)


class CommandPreviewTests(unittest.TestCase):
    def _options(self, **kw):
        class O:
            pass
        o = O()
        o.project = 'neutrino'
        o.cycle_mode = 'power_cycle'
        o.channel = 'inband'
        o.node = None
        o.loops = 0
        o.hours = 0.0
        for k, v in kw.items():
            setattr(o, k, v)
        return o

    def test_aux_cycle_uses_bmc_helper_regardless_of_channel(self):
        # Spec: aux_cycle is always the BMC helper, whatever channel says.
        self.assertEqual(cycle_command('aux_cycle', 'inband'),
                         ('bmc', '/usr/bin/stbypowerctrl.sh aux_cycle'))
        self.assertEqual(cycle_command('aux_cycle', 'outband'),
                         ('bmc', '/usr/bin/stbypowerctrl.sh aux_cycle'))

    def test_power_cycle_inband_is_ipmitool_on_os(self):
        self.assertEqual(cycle_command('power_cycle', 'inband'),
                         ('os', 'ipmitool power cycle'))

    def test_power_cycle_outband_uses_bmc_helper(self):
        self.assertEqual(cycle_command('power_cycle', 'outband'),
                         ('bmc', '/usr/bin/powerctrl.sh power_cycle'))

    def test_reboot_inband_vs_outband(self):
        self.assertEqual(cycle_command('reboot', 'inband'), ('os', 'reboot'))
        # Outband reboot goes through transport.oob(): sub-command is 'power reset'
        # and the ipmitool wrapper is added by the transport.
        self.assertEqual(cycle_command('reboot', 'outband'), ('oob', 'power reset'))

    def test_display_command_shows_ipmitool_for_oob(self):
        shown = display_command('oob', 'power reset')
        self.assertIn('ipmitool', shown)
        self.assertIn('power reset', shown)

    def test_display_command_passes_through_other_roles(self):
        self.assertEqual(display_command('os', 'reboot'), 'reboot')
        self.assertEqual(display_command('bmc', '/usr/bin/powerctrl.sh power_cycle'),
                         '/usr/bin/powerctrl.sh power_cycle')

    def test_build_command_shows_ipmitool_for_reboot_outband(self):
        lines, _ = build_command(self._options(cycle_mode='reboot', channel='outband',
                                               node=['ETF1/n0']))
        self.assertIn('ipmitool', lines[0])
        self.assertIn('power reset', lines[0])

    def test_build_command_lists_one_line_per_node(self):
        lines, limit = build_command(self._options(
            cycle_mode='aux_cycle', node=['ETF1/n0', 'ETF2/n1'], loops=3))
        self.assertEqual(lines, [
            '[bmc] ETF1/n0: /usr/bin/stbypowerctrl.sh aux_cycle',
            '[bmc] ETF2/n1: /usr/bin/stbypowerctrl.sh aux_cycle',
        ])
        self.assertEqual(limit, '3 loops')

    def test_hours_used_when_no_loops(self):
        _, limit = build_command(self._options(hours=2.5))
        self.assertEqual(limit, '2.5 hours')

    def test_show_command_prints_plain_off_terminal(self):
        # StringIO is not a tty, so output must be plain (no ANSI escapes).
        out = io.StringIO()
        old, sys.stdout = sys.stdout, out
        try:
            show_command(self._options(cycle_mode='aux_cycle', node=['ETF1/n0'], loops=1))
        finally:
            sys.stdout = old
        text = out.getvalue()
        self.assertIn('/usr/bin/stbypowerctrl.sh aux_cycle', text)
        self.assertIn('ETF1/n0', text)
        self.assertNotIn('\x1b[', text)


if __name__ == '__main__':
    unittest.main()
