'''
MIT License

Copyright (c) 2024 Kerry Shen

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
'''

from io import SEEK_SET, TextIOWrapper
from typing import Any
from datetime import datetime
import pygame
import copy
import sys

class Model_EventParser:
    TAG: str = 'EventParser'

    __activeSlot: int = 0
    __slots: dict[int, dict[str, int | None]] = {}
    __slotsReady: int | None = None  # Becomes timestamp of last SYN_REPORT on getting one, is reset after read

    def parse_event_line(self, _eventLine: str) -> None:
        eventLine: list[str] = _eventLine.strip().split()
        assert(len(eventLine) == 5)

        timestampStr: str = '{} {}'.format(eventLine[0], eventLine[1])
        timestampMs: int = int(datetime.strptime(timestampStr, '%Y/%m/%d %H:%M:%S.%f').timestamp() * 1000)  # Epoch with timezone offset

        event: dict[str, int] = {'timestamp': timestampMs,
                                 'type': int(eventLine[2], base=16),
                                 'code': int(eventLine[3], base=16),
                                 'value': int(eventLine[4], base=16)}
        
        if event['type'] == 0x0003:  # EV_ABS
            match event['code']:
                # ABS_MT_SLOT
                case 0x002f:
                    self.__select_slot(event['value'])
                # ABS_MT_TRACKING_ID
                case 0x0039:
                    if event['value'] != self.__safe_get_slot(self.__activeSlot)['tracking_id']:
                        self.__init_slot(self.__activeSlot)
                        if event['value'] != 0xffffffff:
                            self.__safe_get_slot(self.__activeSlot)['tracking_id'] = event['value']
                # ABS_MT_POSITION_X
                case 0x0035:
                    self.__safe_get_slot(self.__activeSlot)['x'] = event['value']
                # ABS_MT_POSITION_Y
                case 0x0036:
                    self.__safe_get_slot(self.__activeSlot)['y'] = event['value']
                case _:
                    print('{}: Warning: Unhandled event: type EV_ABS, code {}, value {}'.format(self.TAG, event['code'], event['value']))
        elif event['type'] == 0x0000:  # SYN_REPORT
            self.__ready_slots(event['timestamp'])
        else:
            if event['type'] != 0x0001 and event['code'] != 0x014a:  # Don't care about BTN_TOUCH
                print('{}: Warning: Unhandled event: type {}, code {}, value {}'.format(self.TAG, event['type'], event['code'], event['value']))

    def __init_slot(self, slotID: int) -> None:
        self.__slots[slotID] = {'tracking_id': None,
                               'x': None,
                               'y': None}

    def __safe_get_slot(self, slotID: int) -> dict[str, int | None]:
        # Create slots if not exist
        if slotID not in self.__slots.keys():
            self.__init_slot(slotID)
        return self.__slots[slotID]  # Pass by reference

    def __select_slot(self, slotID: int) -> None:
        self.__activeSlot = slotID

    def __ready_slots(self, timestamp: int) -> None:
        if self.__slotsReady is not None:
            print('{}: Warning: Unread SYN_REPORT, timestamp {}'.format(self.TAG, self.__slotsReady))
        self.__slotsReady = timestamp

    def get_slots(self) -> dict[int, dict[str, int | None]]:
        return self.__slots
    
    def get_slots_ready(self) -> int | None:
        slotsReady: int | None = self.__slotsReady
        self.__slotsReady = None
        return slotsReady


class View_UI:
    TAG: str = 'UI'

    __trails: list[dict[str, Any]] = []
    __persistent_trails: dict[int, dict[str, Any]] = {}

    __trailBg: tuple[int, int, int] = (0, 0, 0)
    __trailColor: tuple[int, int, int] = (255, 0, 0)
    __trailPointRadius: int = 5
    __trailLineWidth: int = 5
    __progressBarBg: tuple[int, int, int] = (255, 255, 255)
    __progressBarFg: tuple[int, int, int] = (0, 255, 0)
    __progressBarTextColor: tuple[int, int, int] = (0, 0, 0)
    __toolbarBg: tuple[int, int, int] = (0, 0, 255)
    __toolbarFg: tuple[int, int, int] = (63, 63, 255)  # TODO: For mouse hovered buttons, not willing to implement this
    __toolbarTextColor: tuple[int, int, int] = (255, 255, 255)
    __progressBarBoundingBoxes: list[dict[str, Any]] = []
    __toolbarBtnBoundingBoxes: list[dict[str, Any]] = []

    def __init__(self, windowWidth: int, windowHeight: int, windowCaption: str, mainProgressBarHeight: int, subProgressBarHeight: int, toolbarHeight: int, trailFadeTimeMs: int) -> None:
        self.__windowSize: tuple[int, int] = windowWidth, windowHeight
        self.__mainProgressBarHeight: int = mainProgressBarHeight
        self.__subProgressBarHeight: int = subProgressBarHeight
        self.__toolbarHeight: int = toolbarHeight
        self.__trailSurfaceSize: tuple[int, int] = windowWidth, windowHeight - mainProgressBarHeight - subProgressBarHeight - toolbarHeight
        self.__trailFadeTimeMs: int = trailFadeTimeMs

        pygame.init()
        self.__windowSurface: pygame.Surface = pygame.display.set_mode(self.__windowSize)
        pygame.display.set_caption(windowCaption)
        self.__trailSurface = pygame.Surface(self.__trailSurfaceSize, flags=pygame.SRCALPHA)
        self.__font: pygame.font.Font = pygame.font.SysFont('Consolas', 15)  # TODO
        self.__toolbarButtons: list[dict[str, Any]] = [{
                'label': 'Pause',
                'width': 60,
                'rightMargin': 10,
                'callback': self.__button_play_pause_callback,
                'custom_data': False
            }, {
                'label': 'Skip',
                'width': 60,
                'rightMargin': 10,
                'callback': self.__button_skip_callback,
                'custom_data': None
            }, {
                'label': 'FF 20',
                'width': 60,
                'rightMargin': 10,
                'callback': self.__button_ff_20_callback,
                'custom_data': None
            }, {
                'label': '1x',
                'width': 60,
                'rightMargin': 10,
                'callback': self.__button_toggle_speed_callback,
                'custom_data': 1
            }]
        self.window_size_changed()

    def __button_play_pause_callback(self, btn: dict[str, Any]) -> tuple[str, Any] | None:
        paused: bool = btn['custom_data']
        btn['custom_data'] = not paused
        btn['label'] = 'Play' if btn['custom_data'] else 'Pause'
        return ('paused', btn['custom_data'])

    def __button_skip_callback(self, btn: dict[str, Any]) -> tuple[str, Any] | None:
        return ('skip_waiting', None)

    def __button_ff_20_callback(self, btn: dict[str, Any]) -> tuple[str, Any] | None:
        return ('skip_events', 20)

    def __button_toggle_speed_callback(self, btn: dict[str, Any]) -> tuple[str, Any] | None:
        speed: int = btn['custom_data']
        btn['custom_data'] = speed + 1 if speed < 10 else 1
        btn['label'] = '{}x'.format(btn['custom_data'])
        return ('set_playback_speed_multiplier', btn['custom_data'])

    def __main_progress_bar_callback(self, relativeCoords: tuple[int, int]) -> tuple[str, Any] | None:
        progressBarWidth: int = self.__windowSize[0]
        return ('set_file_position', relativeCoords[0] / (progressBarWidth - 1))

    def __sub_progress_bar_callback(self, relativeCoords: tuple[int, int]) -> tuple[str, Any] | None:
        return None

    def add_trail(self, start: tuple[int, int] | None, end: tuple[int, int], timestampMs: int) -> None:
        self.__trails.append({
            'start': start,
            'end': end,
            'timestamp': timestampMs,
            'expired': False
        })

    def add_persistent_trail(self, start: tuple[int, int] | None, end: tuple[int, int], id: int) -> None:
        self.__persistent_trails[id] = {
            'start': start,
            'end': end
        }

    def fade_persistent_trail(self, id: int | None = None, timestampMs: int | None = None) -> None:
        if id is not None:
            if id not in self.__persistent_trails.keys():
                return
            if timestampMs is not None:
                self.add_trail(self.__persistent_trails[id]['start'], self.__persistent_trails[id]['end'], timestampMs)
            del self.__persistent_trails[id]
        else:
            if timestampMs is not None:
                for _, trail in self.__persistent_trails.items():
                    self.add_trail(trail['start'], trail['end'], timestampMs)
            self.__persistent_trails.clear()

    def __draw_trail_line_or_circle(self, color: Any, start: tuple[int, int] | None, end: tuple[int, int]) -> None:
        if start is not None:
            pygame.draw.line(self.__trailSurface, color, start, end, self.__trailLineWidth)
        else:
            pygame.draw.circle(self.__trailSurface, color, end, self.__trailPointRadius)

    def update_trails(self, timestampMs: int) -> None:
        self.__trailSurface.fill((0, 0, 0, 0))
        for trail in self.__trails:
            alpha: int = min(round(255 * (1 - (timestampMs - trail['timestamp']) / self.__trailFadeTimeMs)), 255)
            color: tuple[int, int, int, int] = (*self.__trailColor, alpha)
            if alpha <= 0:
                # Remove expired trails LATER
                trail['expired'] = True
                continue
            self.__draw_trail_line_or_circle(color, trail['start'], trail['end'])
        self.__trails = [trail for trail in self.__trails if not trail['expired']]

        for _, trail in self.__persistent_trails.items():
            self.__draw_trail_line_or_circle(self.__trailColor, trail['start'], trail['end'])

        self.__windowSurface.blit(self.__trailSurface, (0, 0))

    def draw_UI(self, mainProgressBarPercentage: float, mainProgressBarText: str, subProgressBarPercentage: float, subProgressBarText: str | None = None) -> None:
        progressBarWidth: int = self.__windowSize[0]
        drawUICoordY: int = self.__trailSurfaceSize[1]
        
        self.__draw_progress_bar(self.__windowSurface, (0, drawUICoordY), (progressBarWidth, self.__mainProgressBarHeight), mainProgressBarPercentage, mainProgressBarText)
        drawUICoordY += self.__mainProgressBarHeight

        self.__draw_progress_bar(self.__windowSurface, (0, drawUICoordY), (progressBarWidth, self.__subProgressBarHeight), subProgressBarPercentage, subProgressBarText)
        drawUICoordY += self.__subProgressBarHeight

        self.__draw_toolbar(self.__windowSurface, (0, drawUICoordY), self.__toolbarHeight)

    def __draw_progress_bar(self, surface: pygame.Surface, coords: tuple[int, int], size: tuple[int, int], percentage: float, text: str | None) -> None:
        progressBarFilledWidth: int = round(size[0] * percentage)
        pygame.draw.rect(surface, self.__progressBarFg, pygame.Rect(*coords, progressBarFilledWidth, size[1]))
        pygame.draw.rect(surface, self.__progressBarBg, pygame.Rect(coords[0] + progressBarFilledWidth, coords[1], size[0] - progressBarFilledWidth, size[1]))
        if text is not None and len(text) > 0:
            surface.blit(self.__font.render(text, True, self.__progressBarTextColor), (10, coords[1] + 10))  # TODO

    def __draw_toolbar(self, surface: pygame.Surface, coords: tuple[int, int], height: int) -> None:
        coordX, coordY = coords
        for btn in self.__toolbarButtons:
            pygame.draw.rect(surface, self.__toolbarBg, pygame.Rect(coordX, coordY, btn['width'], height))
            surface.blit(self.__font.render(btn['label'], True, self.__toolbarTextColor), (coordX + 10, coordY + 10))  # TODO
            coordX += btn['width'] + btn['rightMargin']

    def handle_click(self, coords: tuple[int, int]) -> tuple[str, Any] | None:
        for boundingBox in self.__progressBarBoundingBoxes:
            if boundingBox['rect'].collidepoint(*coords):
                return boundingBox['callback']((coords[0] - boundingBox['rect'].left, coords[1] - boundingBox['rect'].top))
        for boundingBox in self.__toolbarBtnBoundingBoxes:
            if boundingBox['rect'].collidepoint(*coords):
                return boundingBox['btn']['callback'](boundingBox['btn'])
        return None

    def __generate_toolbar_bounding_boxes(self, toolbarCoords: tuple[int, int]) -> None:
        coordX, coordY = toolbarCoords
        self.__toolbarBtnBoundingBoxes.clear()
        for btn in self.__toolbarButtons:
            self.__toolbarBtnBoundingBoxes.append({'btn': btn,
                                                   'rect': pygame.Rect(coordX, coordY, btn['width'], self.__toolbarHeight)})
            coordX += btn['width'] + btn['rightMargin']

    def __generate_progress_bar_bounding_boxes(self, progressBarCoords: tuple[int, int]) -> None:
        progressBarWidth: int = self.__windowSize[0]
        coordX, coordY = progressBarCoords
        self.__progressBarBoundingBoxes.clear()

        self.__progressBarBoundingBoxes.append({'callback': self.__main_progress_bar_callback,
                                                'rect': pygame.Rect(coordX, coordY, progressBarWidth, self.__mainProgressBarHeight)})
        coordY += self.__mainProgressBarHeight

        self.__progressBarBoundingBoxes.append({'callback': self.__sub_progress_bar_callback,
                                                'rect': pygame.Rect(coordX, coordY, progressBarWidth, self.__subProgressBarHeight)})

    def window_size_changed(self) -> None:
        self.__generate_progress_bar_bounding_boxes((0, self.__trailSurfaceSize[1]))
        self.__generate_toolbar_bounding_boxes((0, self.__trailSurfaceSize[1] + self.__mainProgressBarHeight + self.__subProgressBarHeight))

    def get_trail_surface_size(self) -> tuple[int, int]:
        return self.__trailSurface.get_size()

    def fill_window(self, color: tuple[int, int, int] | None = None) -> None:
        self.__windowSurface.fill(color if color is not None else self.__trailBg)


class Controller:
    TAG: str = 'Controller'

    __file: TextIOWrapper | None = None
    __fileInitialPosition: int = 0
    __fileTotalLines: int = 0
    __fileNextLineNum: int = 0  # Index starts with 0
    __previousSlots: dict[int, dict[str, int | None]] = {}
    __previousSynEventTmstmp: int | None = None
    __waitingStartTmstmp: int = 0
    __waitingTargetTmstmp: int | None = None
    __waitingTimeDivisor: int = 1  # For changing playback speed
    __skipWaitingFlag: bool = False  # Jump to end of waiting
    __skipWaitingTimeOffsetFlag: bool = False  # Don't adjust for timing in __realtime_event_tick, useful when unpausing
    __currentEventLine: str = ''
    __paused: bool = False
    __eventProcessingQuotaMs: int = 8  # TODO

    def __init__(self, eventParser: Model_EventParser, viewUI: View_UI, eventXResolution: int, eventYResolution: int) -> None:
        self.__eventParser: Model_EventParser = eventParser
        self.__viewUI: View_UI = viewUI
        self.__eventXRes: int = eventXResolution
        self.__eventYRes: int = eventYResolution
        self.__clock = pygame.time.Clock()

    def __scale_coords(self, x: int, y: int) -> tuple[int, int]:
        surfaceW, surfaceH = self.__viewUI.get_trail_surface_size()
        return (x * (surfaceW - 1) // (self.__eventXRes - 1),
                y * (surfaceH - 1) // (self.__eventYRes - 1))

    def __safe_get_slot(self, slots: dict[int, dict[str, int | None]], slotID: int) -> dict[str, int] | None:
        if slotID not in slots.keys():
            return None
        if slots[slotID]['tracking_id'] is None:
            return None
        for key, value in slots[slotID].items():
            if value is None:
                if key != 'tracking_id':
                    print('{}: Warning: Bogus event: None coordinate(s) under non-None tracking ID'.format(self.TAG))
                return None
        return slots[slotID]  # type: ignore

    def __draw_slots(self, slots: dict[int, dict[str, int | None]], previousSlots: dict[int, dict[str, int | None]], currentTimestampMs: int) -> None:
        assert(len(previousSlots) <= len(slots))  # Slots don't shrink, they only grow when required.
        for slotID in slots.keys():
            slot: dict[str, int] | None = self.__safe_get_slot(slots, slotID)
            previousSlot: dict[str, int] | None = self.__safe_get_slot(previousSlots, slotID)
            if slot is None:
                if previousSlot is not None:
                    self.__viewUI.fade_persistent_trail(slotID, currentTimestampMs)
            else:
                if previousSlot is not None:
                    if previousSlot['tracking_id'] == slot['tracking_id']:
                        self.__viewUI.add_trail(self.__scale_coords(previousSlot['x'], previousSlot['y']), \
                                               self.__scale_coords(slot['x'], slot['y']), \
                                               currentTimestampMs)
                    else:
                        self.__viewUI.fade_persistent_trail(slotID, currentTimestampMs)
                self.__viewUI.add_persistent_trail(None, self.__scale_coords(slot['x'], slot['y']), slotID)

    def __realtime_event_tick(self) -> tuple[float, str] | None:
        assert(self.__file is not None)
        currentMs: int = pygame.time.get_ticks()
        waitingTimeOffset: int = 0

        if self.__skipWaitingFlag:
            self.__waitingTargetTmstmp = currentMs
            self.__waitingStartTmstmp = currentMs
            self.__previousSynEventTmstmp = None
            self.__skipWaitingFlag = False

        if self.__waitingTargetTmstmp is not None:
            if currentMs < self.__waitingTargetTmstmp:
                return ((currentMs - self.__waitingStartTmstmp) / (self.__waitingTargetTmstmp - self.__waitingStartTmstmp) if self.__waitingTargetTmstmp != self.__waitingStartTmstmp else 1,
                        self.__currentEventLine)
            else:
                waitingTimeOffset = self.__waitingTargetTmstmp - currentMs
                self.__waitingTargetTmstmp = None

                slots: dict[int, dict[str, int | None]] = self.__eventParser.get_slots()
                self.__draw_slots(slots, self.__previousSlots, currentMs)
                self.__previousSlots = copy.deepcopy(slots)

        if self.__skipWaitingTimeOffsetFlag:
            waitingTimeOffset = 0
            self.__skipWaitingTimeOffsetFlag = False
        # print('{}: Debug: waitingTimeOffset: {}'.format(self.TAG, waitingTimeOffset))

        eventLine: str | None = self.__file_read_line()
        if eventLine is None:
            return None
        self.__currentEventLine = eventLine
        self.__eventParser.parse_event_line(eventLine)

        synEventTimestamp: int | None = self.__eventParser.get_slots_ready()
        if synEventTimestamp is not None:
            if self.__previousSynEventTmstmp is not None:
                self.__waitingStartTmstmp = currentMs
                self.__waitingTargetTmstmp = round((synEventTimestamp - self.__previousSynEventTmstmp) / self.__waitingTimeDivisor) + currentMs + waitingTimeOffset
            else:  # Usually executed only once
                slots: dict[int, dict[str, int | None]] = self.__eventParser.get_slots()
                self.__draw_slots(slots, self.__previousSlots, currentMs)
                self.__previousSlots = copy.deepcopy(slots)
            
            self.__previousSynEventTmstmp = synEventTimestamp        
        return (1, self.__currentEventLine)

    # Effect includes __skip_waiting_time_offset
    def __skip_waiting(self) -> None:
        self.__skipWaitingFlag = True

    def __skip_waiting_time_offset(self) -> None:
        self.__skipWaitingTimeOffsetFlag = True

    def __update_display(self, currentTimestampMs: int, mainProgressBarPercentage: float, mainProgressBarText: str, subProgressBarPercentage: float) -> None:
        self.__viewUI.fill_window()
        self.__viewUI.update_trails(currentTimestampMs)
        self.__viewUI.draw_UI(mainProgressBarPercentage, mainProgressBarText, subProgressBarPercentage)
        pygame.display.update()

    def main_loop(self) -> None:  # Timing is difficult, as is my life.
        lastFrameEndTmstmpMs: int = pygame.time.get_ticks()
        finishEventProcessingTmstmpMs: int = lastFrameEndTmstmpMs
        timeBuffer: int = 0
        waitingPercentage: float | None = 0
        currentEventLine: str = ''
        lastEventLine: str = ''
        while True:
            frameStartTmstmpMs: int = pygame.time.get_ticks()
            eofReached: bool = False  # TODO

            if not self.__paused:
                lastNopTimeMs: int = frameStartTmstmpMs - lastFrameEndTmstmpMs
                if lastNopTimeMs > 0:
                    self.__eventProcessingQuotaMs = lastNopTimeMs
                if timeBuffer > 0:
                    while pygame.time.get_ticks() < frameStartTmstmpMs + self.__eventProcessingQuotaMs:
                        ret = self.__realtime_event_tick()
                        if ret is None:
                            eofReached = True
                            break
                        lastEventLine = currentEventLine
                        waitingPercentage, currentEventLine = ret
                    if eofReached:
                        break  # Break to function return
                finishEventProcessingTmstmpMs = pygame.time.get_ticks()
                timeBuffer += lastNopTimeMs - (finishEventProcessingTmstmpMs - frameStartTmstmpMs)
            else:
                finishEventProcessingTmstmpMs = pygame.time.get_ticks()
            # print('{}: Debug: eventProcessingTime: {}\ttimeBuffer: {}\tFramerate: {}'.format(self.TAG, finishEventProcessingTmstmpMs - frameStartTmstmpMs, str(timeBuffer).rjust(3), self.__clock.get_fps()))

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit()
                if event.type == pygame.MOUSEBUTTONDOWN:
                    clickEvent: tuple[str, Any] | None = self.__viewUI.handle_click(event.pos)
                    if clickEvent is not None:
                        match clickEvent[0]:
                            case 'paused':
                                self.__paused = clickEvent[1]
                                self.__skip_waiting_time_offset()
                            case 'skip_waiting':
                                self.__skip_waiting()
                            case 'skip_events':
                                for _ in range(clickEvent[1]):
                                    self.__file_read_line()
                                self.__skip_waiting()
                            case 'set_playback_speed_multiplier':
                                self.__waitingTimeDivisor = clickEvent[1]
                            case 'set_file_position':
                                lineIndex: int = round(self.__fileTotalLines * clickEvent[1])
                                self.__file_goto_line(lineIndex)
                                print(lineIndex)  # TODO: This requires a margin at the two ends of the progress bar
                                self.__viewUI.fade_persistent_trail(None, finishEventProcessingTmstmpMs)
                                self.__skip_waiting()
                            case _:
                                print('{}: Warning: Unhandled clickEvent {}, value {}'.format(self.TAG, *clickEvent))
            assert(waitingPercentage is not None)
            self.__update_display(finishEventProcessingTmstmpMs, self.__fileNextLineNum / self.__fileTotalLines, lastEventLine.strip(), waitingPercentage)

            lastFrameEndTmstmpMs = pygame.time.get_ticks()
            self.__clock.tick(120)

    def load_file(self, file: TextIOWrapper) -> None:  # TODO
        self.__file = file
        self.__fileInitialPosition = file.tell()
        self.__fileTotalLines = self.__file_get_total_lines()
        self.__fileNextLineNum = 0

    def __file_get_total_lines(self) -> int:
        assert(self.__file is not None)
        totalLines: int = 0
        while True:
            if not self.__file.readline():
                break
            totalLines += 1
        self.__file.seek(self.__fileInitialPosition, SEEK_SET)
        return totalLines

    def __file_read_line(self) -> str | None:
        assert(self.__file is not None)
        line: str = self.__file.readline()
        if line:
            self.__fileNextLineNum += 1
            return line
        return None

    # Next __file_read_line would return the line specified; index of first line is 0
    def __file_goto_line(self, lineIndex: int) -> None:
        assert(self.__file is not None)
        lineIndex = max(lineIndex, 0)  # Min is 0
        lineIndex = min(lineIndex, self.__fileTotalLines)  # Max is EOF
        if lineIndex == self.__fileNextLineNum:
            return
        elif lineIndex > self.__fileNextLineNum:
            for _ in range(lineIndex - self.__fileNextLineNum):
                self.__file_read_line()
        else:
            self.__file.seek(self.__fileInitialPosition, SEEK_SET)
            self.__fileNextLineNum = 0
            for _ in range(lineIndex):
                self.__file_read_line()


if __name__ == '__main__':
    eventParser = Model_EventParser()
    viewUI = View_UI(450, 1080, 'ActionReplay', 40, 10, 30, 1000)
    controller = Controller(eventParser, viewUI, 1080 * 16, 2400 * 16)

    with open('Your_Events_Here.txt', 'r') as f:
        controller.load_file(f)
        controller.main_loop()
