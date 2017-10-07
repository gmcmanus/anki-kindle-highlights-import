from datetime import datetime
import re
from collections import namedtuple

from anki.notes import Note
from aqt import mw
from aqt.utils import getFile, showInfo, showText
from aqt.qt import QAction


def main():
    action = QAction('Import Kindle highlights', mw)
    action.triggered.connect(import_highlights)
    mw.form.menuTools.addAction(action)


def import_highlights():
    path = getFile(mw, 'Open Kindle clippings', cb=None, filter='Text file (*.txt)', key='KindleHighlights')

    with open(path, encoding='utf-8') as file:
        clippings, bad_clippings = parse_clippings(file)

    if bad_clippings:
        showText(
            f'The following {len(bad_clippings)} clippings could not be parsed:\n\n' +
            '\n==========\n'.join(bad_clippings))

    config = mw.addonManager.getConfig(__name__)

    highlight_clippings = list(highlights_only(clippings))
    clippings_to_add = after_last_added(highlight_clippings, last_added_datetime(config))

    model = mw.col.models.byName('Cloze')

    clipping = None

    for clipping in clippings_to_add:
        note = Note(mw.col, model)
        note.fields = list(fields(clipping, model))
        mw.col.addNote(note)

    if clipping:
        config['last_added'] = added_datetime(clipping).isoformat()
        mw.addonManager.writeConfig(__name__, config)

    def info():
        if clippings_to_add:
            yield f'{len(clippings_to_add)} new highlights imported'

        num_old_highlights = len(highlight_clippings) - len(clippings_to_add)
        if num_old_highlights:
            yield f'{num_old_highlights} old highlights ignored'

        num_not_highlights = len(clippings) - len(highlight_clippings)
        if num_not_highlights:
            yield f'{num_not_highlights} non-highlight clippings ignored'

    info_strings = list(info())
    if info_strings:
        showInfo(', '.join(info_strings) + '.')
    elif bad_clippings:
        showInfo('No other clippings found.')
    else:
        showInfo('No clippings found.')


Clipping = namedtuple('Clipping', ('kind', 'document', 'page', 'location', 'added', 'content'))


def parse_clippings(file):
    clippings = []
    bad_clippings = []

    current_clipping_lines = []
    for line in file:
        if line != '==========\n':
            current_clipping_lines.append(line)
            continue

        string = ''.join(current_clipping_lines)
        current_clipping_lines.clear()

        clipping = parse_clipping(string)

        if clipping:
            clippings.append(clipping)
        else:
            bad_clippings.append(string)

    if current_clipping_lines:
        bad_clippings.append(''.join(current_clipping_lines))

    return clippings, bad_clippings


def parse_clipping(string):
    match = re.fullmatch(CLIPPING_PATTERN, string)
    if not match:
        return None
    return Clipping(**match.groupdict())


CLIPPING_PATTERN = r'''\ufeff?(?P<document>.*)
- Your (?P<kind>.*) on (?:page (?P<page>.*) \| )?(?:Location (?P<location>.*) \| )?Added on (?P<added>.*)

(?P<content>.*)
?'''


def after_last_added(clippings, last_added):
    if not last_added:
        return clippings

    def reversed_clippings_after_last_added():
        for clipping in reversed(clippings):
            clipping_added = added_datetime(clipping)
            if clipping_added <= last_added:
                return
            yield clipping

    clippings_after_last_added = list(reversed_clippings_after_last_added())
    clippings_after_last_added.reverse()
    return clippings_after_last_added


def added_datetime(clipping):
    return datetime.strptime(clipping.added, '%A, %B %d, %Y %I:%M:%S %p')


def last_added_datetime(config):
    last_added_config = config.get('last_added')
    return datetime.strptime(last_added_config, '%Y-%m-%dT%H:%M:%S') if last_added_config else None


def highlights_only(clippings):
    for clipping in clippings:
        if clipping.kind == 'Highlight':
            yield clipping


def fields(clipping, model):
    for field in mw.col.models.fieldNames(model):
        if field == 'Text':
            yield clipping.content
        elif field == 'Extra':
            yield ''
        elif field == 'Source':
            yield 'Kindle {kind} from {document}{page}{location} added {added}'.format(
                kind=clipping.kind.lower(),
                document=clipping.document,
                page=' page ' + clipping.page if clipping.page is not None else '',
                location=' location ' + clipping.location if clipping.location is not None else '',
                added=clipping.added,
            )
        else:
            raise ValueError('Unknown field: ' + field)


main()
