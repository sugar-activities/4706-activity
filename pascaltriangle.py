# coding=utf-8
#
# Pascal Triangle
# Copyright (C) Philip Withnall 2013 <philip@tecnocode.co.uk>
#
# Pascal Triangle is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Pascal Triangle is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Pascal Triangle.  If not, see <http://www.gnu.org/licenses/>.

from sugar3.activity import activity, widgets
from sugar3.graphics.alert import Alert
from sugar3.graphics.icon import Icon
from sugar3.graphics.toolbarbox import ToolbarBox
from sugar3.graphics.toolbutton import ToolButton
from sugar3.graphics.toggletoolbutton import ToggleToolButton
import math
import random
from gi.repository import Gtk, Gdk
import cairo
from gettext import gettext as _
import pickle
import logging


class PascalTriangleActivity(activity.Activity):
    """Pascal's Triangle arithmetic activity.

    This is a simple Sugar activity which presents Pascal's Triangle in the
    form of a game, requiring the user to fill in blank cells in the triangle
    until it is complete.

    It supports multiple sizes of triangle, and also supports highlighting the
    cells which contribute to the currently selected one.
    """
    def __init__(self, handle):
        super(PascalTriangleActivity, self).__init__(handle)

        self.max_participants = 1  # No sharing

        # Set up logging first.
        self._logger = logging.getLogger('pascal-triangle-activity')

        # Create the standard activity toolbox.
        toolbar_box = ToolbarBox()
        self.set_toolbar_box(toolbar_box)
        toolbar_box.show()

        main_toolbar = toolbar_box.toolbar

        activity_toolbar_button = widgets.ActivityToolbarButton(self)
        main_toolbar.insert(activity_toolbar_button, 0)
        activity_toolbar_button.show()

        new_game_button = NewGameButton(self)
        new_game_button.show()
        main_toolbar.insert(new_game_button, -1)

        hint_button = HintButton(self)
        hint_button.show()
        main_toolbar.insert(hint_button, -1)
        self._hint_button = hint_button

        separator = Gtk.SeparatorToolItem()
        separator.props.draw = True
        separator.set_expand(False)
        separator.show()
        main_toolbar.insert(separator, -1)

        slider = Gtk.HScale()
        slider.props.digits = 0  # integers only
        slider.props.draw_value = False
        slider.props.has_origin = False
        slider.set_range(2, 10)
        slider.set_increments(1, 2)
        slider.set_value(5)  # initial triangle size
        slider.set_size_request(150, 15)
        slider.show()

        toolitem = Gtk.ToolItem()
        toolitem.add(slider)
        toolitem.show()
        main_toolbar.insert(toolitem, -1)

        separator = Gtk.SeparatorToolItem()
        separator.props.draw = False
        separator.set_expand(True)
        separator.show()
        main_toolbar.insert(separator, -1)

        stop_button = widgets.StopButton(self)
        stop_button.show()
        main_toolbar.insert(stop_button, -1)

        # Create a new GTK+ drawing area
        drawing_area = Gtk.DrawingArea()
        drawing_area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK |
                                Gdk.EventMask.KEY_PRESS_MASK)
        drawing_area.set_can_focus(True)
        drawing_area.connect('button-press-event',
                             self.__drawing_area_button_press_cb, None)
        drawing_area.connect('key-press-event',
                             self.__drawing_area_key_press_cb, None)
        drawing_area.connect('draw', self.__drawing_area_draw_cb, None)

        # Create an overlay and a slider to allow the triangle size to be
        # adjusted. This is the number of cells on the triangle's base
        # (equivalently, the number of rows in the triangle).
        overlay = Gtk.Overlay()
        overlay.add(drawing_area)
        overlay.show()

        self._triangle_size = int(slider.get_value())
        slider.connect('value-changed', self.__slider_value_changed_cb, None)
        self._slider = slider

        # Parent and show the drawing area.
        self.set_canvas(overlay)
        drawing_area.show()
        self._drawing_area = drawing_area

        # Start with hints off and no 'game over' alert.
        self._show_hints = False
        self._alert = None

        # Various initial declarations.
        self._padding = 10.0  # Cairo units; padding around the drawing area
        self._blank_cells = []
        self._current_cell = (-1, -1)
        self._current_cell_text = ''

        # Start a new game.
        self.start_game()

    def start_game(self):
        """Start a new game, clearing the previous game and any alerts."""
        # Focus the drawing area so it can receive keyboard events.
        self._drawing_area.grab_focus()

        # Clear any alerts from the previous game.
        if self._alert:
            self.remove_alert(self._alert)
            self._alert = None

        # Set the currently selected cell (which the user's clicked on).
        # Default to no selection (-1, -1).
        self._current_cell = (-1, -1)
        self._current_cell_text = ''

        # Generate a list of blank cells which the user needs to fill in.
        self._blank_cells = self._generate_blank_cell_list()

        self._drawing_area.queue_draw()

    def read_file(self, file_path):
        """Read a saved game from the journal.

        If this fails, the current game state will be left untouched. If extra
        state over what was expected is present in the save file, it will be
        ignored. For documentation on the save format, see write_file().
        """
        obj = None
        try:
            with open(file_path, 'rb') as file_fd:
                obj = pickle.load(file_fd)
                if len(obj) < 5:
                    raise pickle.UnpicklingError, 'Invalid tuple.'
        except EnvironmentError as err:
            self._logger.warning('Error reading save file ‘%s’: %s' %
                                 (file_path, err))
            return
        except pickle.UnpicklingError as err:
            self._logger.warning('Malformed save file ‘%s’: %s' %
                                 (file_path, err))
            return

        # Restore the UI state. Setting the triangle size will start a new
        # game, so we must restore other state afterwards. From this point
        # onwards, the code can't fail.
        triangle_size = obj[0]
        self._slider.set_value(triangle_size)

        show_hints = obj[4]
        self._hint_button.set_active(show_hints)

        # Access the obj elements by index so that we don't fail if obj has
        # more than the expected number of elements (e.g. if we've somehow
        # got a save file from a newer version of the activity which saves
        # more state).
        self._blank_cells = obj[1]
        self._current_cell = obj[2]
        self._current_cell_text = obj[3]

        # Redraw everything.
        self._drawing_area.queue_draw()

    def write_file(self, file_path):
        """Write a game to the journal.

        The game state is pickled as a tuple of at least 5 elements. This
        format may be extended in future by appending elements to the tuple;
        read_file() is guaranteed to ignore extra tuple elements. The existing
        tuple elements must be stable, though.
        """
        obj = (
            self._triangle_size,
            self._blank_cells,
            self._current_cell,
            self._current_cell_text,
            self._show_hints,
        )

        try:
            with open(file_path, 'wb') as file_fd:
                pickle.dump(obj, file_fd, pickle.HIGHEST_PROTOCOL)
        except EnvironmentError as err:
            self._logger.warning('Error saving game: %s' % err)

    def _update_current_cell(self, index):
        """Change position of the currently selected cell and clear any pending
           text edits."""
        if index != self._current_cell:
            self._current_cell = index
            self._current_cell_text = ''
            self._drawing_area.queue_draw()

    def _calculate_number_of_cells(self):
        """Calculate the number of cells in the triangle.

        This is the Nth triangle number, where N is the triangle_size. The
        formula for this is 1/2*N*(N+1).
        """
        return self._triangle_size * (self._triangle_size + 1) / 2

    def _generate_blank_cell_list(self):
        """Generate a non-empty list of random cell indices.

        All cells are guaranteed to exist in the current triangle and are
        guaranteed to be unique.
        """
        blank_cells = []

        # Generate a number of coordinates for blank cells, between 1 cell and
        # the entire triangle.
        num_blanks = random.randint(1, self._calculate_number_of_cells())
        for i in range(num_blanks):
            row_index = random.randint(0, self._triangle_size - 1)
            column_index = random.randint(0, row_index)
            blank_cells.append((row_index, column_index))

        # Remove duplicates from the list. We're guaranteed to have a non-empty
        # list after this.
        return list(set(blank_cells))

    def _calculate_pascal_number(self, index):
        """Calculate the Pascal number for the (row, column) cell.

        row and column are both 0-based. This is equivalent to calculating the
        binomial coefficient of (row choose column).
        """
        row = index[0]
        column = index[1]

        num = math.factorial(row)
        denom = math.factorial(column) * math.factorial(row - column)
        return num / denom

    def __drawing_area_button_press_cb(self, widget, event, data=None):
        """Handle a mouse button press in the drawing area."""
        # Check whether the click fell within a cell; if so, change the cell
        # selection.
        if event.type != Gdk.EventType.BUTTON_PRESS:
            return

        # There may be a more efficient way of doing this, but this works and
        # is simple enough. Iterate through the cells and check whether the
        # click was within a given radius of the cell centre.
        widget_height = widget.get_allocated_height()
        base_width = widget.get_allocated_width() - 2.0 * self._padding
        triangle_height = widget_height - 2.0 * self._padding
        cell_width = base_width / self._triangle_size
        cell_height = 3.0 * (triangle_height / (2 * self._triangle_size + 1))

        radius = min(cell_width, cell_height) / 2.0

        for row_index in range(self._triangle_size):
            row_order = row_index + 1
            for column_index in range(row_order):
                index = (row_index, column_index)
                cell_position = self._calculate_cell_position(base_width,
                                                              cell_width,
                                                              cell_height,
                                                              index)

                if self._is_cursor_in_radius(radius, cell_position,
                                             (event.x, event.y)):
                    # Found the cell.
                    self._update_current_cell(index)
                    return True

        # No cell found? Clear the current cell.
        self._update_current_cell((-1, -1))
        return True

    def _is_cursor_in_radius(self, radius, cell_position, cursor_position):
        """Calculate whether cursor_position falls within radius of
           cell_position."""
        actual_radius_sq = (cell_position[0] - cursor_position[0]) ** 2 + \
                           (cell_position[1] - cursor_position[1]) ** 2
        return (actual_radius_sq <= radius ** 2)

    def __drawing_area_key_press_cb(self, widget, event, data=None):
        """Handle a keyboard button press in the drawing area."""
        if event.type != Gdk.EventType.KEY_PRESS:
            return False

        # Give up if any modifiers are set.
        if event.state != 0:
            return True

        digit_keyvals = [
            Gdk.KEY_0,
            Gdk.KEY_1,
            Gdk.KEY_2,
            Gdk.KEY_3,
            Gdk.KEY_4,
            Gdk.KEY_5,
            Gdk.KEY_6,
            Gdk.KEY_7,
            Gdk.KEY_8,
            Gdk.KEY_9,
        ]
        control_keyvals = [
            # Only backspace is supported at the moment.
            Gdk.KEY_BackSpace,
        ]

        # Handle digit presses. Note we don't currently support infix editing
        # and we clamp to 2 digits.
        if event.keyval in digit_keyvals:
            if len(self._current_cell_text) < 2:
                digit = digit_keyvals.index(event.keyval)
                self._current_cell_text += '%i' % digit
                widget.queue_draw()

            # Check whether the answer is correct.
            self._check_current_cell_text()

            return True
        # Otherwise, handle the control character
        elif event.keyval in control_keyvals:
            if event.keyval == Gdk.KEY_BackSpace:
                self._current_cell_text = self._current_cell_text[:-1]
                widget.queue_draw()
            return True

        # If the key pressed wasn't a digit or control character, ignore it.
        return True

    def __drawing_area_draw_cb(self, widget, ctx, data=None):
        """Redraw the drawing area and all its contents."""
        # Widget allocation and sizes. The cell_height is calculated weirdly
        # because the cells interlock as they tesselate; so for 2 rows, the
        # bottom third of the top row overlaps with the top third of the bottom
        # row.
        widget_height = widget.get_allocated_height()
        base_width = widget.get_allocated_width() - 2.0 * self._padding
        triangle_height = widget_height - 2.0 * self._padding
        cell_width = base_width / self._triangle_size
        cell_height = 3.0 * (triangle_height / (2 * self._triangle_size + 1))

        # Set up drawing style.
        ctx.set_line_width(4)
        ctx.set_line_join(cairo.LINE_JOIN_ROUND)

        # Draw the triangle rows from the top down. The row_order is the number
        # of cells in the row (increasing from 1 to triangle_size, inclusive).
        for row_index in range(self._triangle_size):
            row_order = row_index + 1
            for column_index in range(row_order):
                index = (row_index, column_index)

                # Calculate the cell position.
                (cell_x, cell_y) = self._calculate_cell_position(base_width,
                                                                 cell_width,
                                                                 cell_height,
                                                                 index)

                # Move to the cell position and draw the cell.
                ctx.move_to(cell_x, cell_y)
                self._draw_cell(ctx, index, cell_width, cell_height)

        return True

    def _calculate_cell_position(self, base_width, cell_width,
                                 cell_height, index):
        """Calculate the cell position.

        Add an offset every odd row so the triangle is balanced. Each row is
        only 2/3 of cell_height because the hexagons interlock as they
        tesselate.
        """
        cell_x = (self._padding +
                  base_width / 2.0 - (cell_width / 2.0 * index[0]) +
                  cell_width * index[1])
        cell_y = (self._padding + cell_height / 2.0 +
                  (cell_height * index[0] * (2.0 / 3.0)))
        return (cell_x, cell_y)

    def _get_cell_background(self, index):
        """Get the background colour to use for the given cell."""
        if index == self._current_cell:
            # Currently selected cell.
            return cairo.SolidPattern(0.541, 0.886, 0.204)  # green
        elif (self._show_hints and self._current_cell != (-1, -1) and
              (self._current_cell[1] == 0 or
               self._current_cell[1] == self._current_cell[0]) and
              (index[1] == 0 or index[1] == index[0])):
            # Hint all edge cells if the currently selected cell is on an edge.
            return cairo.SolidPattern(0.447, 0.624, 0.812)  # blue
        elif (self._show_hints and index[0] == self._current_cell[0] - 1 and
              (index[1] == self._current_cell[1] - 1 or
               index[1] == self._current_cell[1])):
            # Hint the two cells above the currently selected cell.
            return cairo.SolidPattern(0.988, 0.914, 0.310)  # yellow
        else:
            # Non-selected, normal cell background.
            return cairo.SolidPattern(1.0, 1.0, 1.0)  # white

    def _draw_cell(self, ctx, index, cell_width, cell_height):
        """Draw a single cell.

        This draws the indexth cell at the current position in the given Cairo
        context. The cell width and height are as given.
        """
        centre = ctx.get_current_point()

        # Draw the cell outline as a hexagon and fill it.
        ctx.rel_move_to(0.0, -cell_height / 2.0)
        ctx.rel_line_to(cell_width / 2.0, cell_height / 3.0)
        ctx.rel_line_to(0.0, cell_height / 3.0)
        ctx.rel_line_to(-cell_width / 2.0, cell_height / 3.0)
        ctx.rel_line_to(-cell_width / 2.0, -cell_height / 3.0)
        ctx.rel_line_to(0.0, -cell_height / 3.0)
        ctx.close_path()

        ctx.set_source_rgb(0.0, 0.0, 0.0)
        ctx.stroke_preserve()

        ctx.set_source(self._get_cell_background(index))
        ctx.fill()

        # Write its number if it's a non-empty cell. If it's an empty cell,
        # write a question mark unless it's the selected cell.
        cell_text = None
        if not index in self._blank_cells:
            cell_text = str(self._calculate_pascal_number(index))
            ctx.set_source_rgb(0.0, 0.0, 0.0)  # black
        elif index != self._current_cell:
            # TRANS: This is the text shown in cells which haven't yet
            # been filled in by the user.
            cell_text = _('?')
            ctx.set_source_rgb(0.4, 0.4, 0.4)  # grey
        else:
            cell_text = self._current_cell_text
            ctx.set_source_rgb(0.8, 0.0, 0.0)  # red

        if cell_text is not None:
            # Rule of thumb to scale the font size with the cells.
            font_size = int(50.0 / (float(self._triangle_size) / 5.0))

            extents = ctx.text_extents(cell_text)
            ctx.move_to(centre[0] - extents[2] / 2.0,
                        centre[1] + extents[3] / 2.0)
            ctx.set_font_size(font_size)
            ctx.show_text(cell_text)

    def _check_current_cell_text(self):
        """Check the user-entered text for the current cell.

        If it matches the expected value, also check to see if the user's
        filled in all blank cells and hence has won.
        """

        # Check whether the answer is correct. If so, change the cell to be
        # uneditable.
        expected_num = self._calculate_pascal_number(self._current_cell)
        if int(self._current_cell_text) == expected_num:
            self._blank_cells.remove(self._current_cell)
            self._update_current_cell((-1, -1))

        # Check whether all blank cells have been filled.
        if len(self._blank_cells) == 0:
            alert = Alert()
            alert.props.title = _('You\'ve won!')
            alert.props.msg = _('Well done! You\'ve completed the Pascal '
                                'Triangle. Do you want to play again?')
            icon = Icon(icon_name='emblem-favorite')
            alert.props.icon = icon
            icon.show()

            icon = Icon(icon_name='add')
            alert.add_button(Gtk.ResponseType.ACCEPT, _('New Game'), icon)
            icon.show()

            alert.connect('response', self.__alert_response_cb)

            alert.show()
            self._alert = alert
            self.add_alert(alert)

    def __alert_response_cb(self, alert, response_id):
        """Callback from the 'game over' alert."""
        self.start_game()

    def get_show_hints(self):
        """Get whether hints should be rendered."""
        return self._show_hints

    def set_show_hints(self, val):
        """Set whether hints should be rendered."""
        if self._show_hints != val:
            self._show_hints = val
            self._drawing_area.queue_draw()

    show_hints = property(get_show_hints, set_show_hints)

    def __slider_value_changed_cb(self, widget, data=None):
        """Handle value changes on the triangle size slider."""
        new_triangle_size = int(widget.get_value())

        if new_triangle_size != self._triangle_size:
            # Start a new game with the new triangle size.
            self._triangle_size = new_triangle_size
            self.start_game()


class NewGameButton(ToolButton):
    """New Game toolbar button."""
    def __init__(self, parent_activity, **kwargs):
        ToolButton.__init__(self, 'add', **kwargs)
        self.props.tooltip = _('New Game')
        self.props.accelerator = '<Ctrl>N'
        self.connect('clicked', self.__new_game_button_clicked_cb,
                     parent_activity)

    def __new_game_button_clicked_cb(self, button, parent_activity):
        """Callback for the button to start a new game."""
        parent_activity.start_game()


class HintButton(ToggleToolButton):
    """Show Hints toolbar toggle button."""
    def __init__(self, parent_activity, **kwargs):
        ToggleToolButton.__init__(self, 'show-hints', **kwargs)
        #self.props.tooltip = 'Show Hints'
        self.set_tooltip(_('Show Hints'))

        # Add an accelerator. In later versions of Sugar, we can just set the
        # 'accelerator' property instead.
        #self.props.accelerator = '<Ctrl>H'
        accel_group = parent_activity.get_toplevel().sugar_accel_group
        keyval, mask = Gtk.accelerator_parse('<Ctrl>H')
        # the accelerator needs to be set at the child, so the Gtk.AccelLabel
        # in the palette can pick it up.
        accel_flags = Gtk.AccelFlags.LOCKED | Gtk.AccelFlags.VISIBLE
        self.get_child().add_accelerator('clicked', accel_group,
                                         keyval, mask, accel_flags)

        self.connect('clicked', self.__hint_button_clicked_cb, parent_activity)

    def __hint_button_clicked_cb(self, button, parent_activity):
        """Callback for the button to toggle the hint state."""
        parent_activity.show_hints = self.get_active()
