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
        showText('The following clippings could not be parsed:\n\n' + '\n==========\n'.join(bad_clippings))

    notes_added = 0

    for clipping in clippings:
        if clipping.kind != 'Highlight':
            continue

        model = mw.col.models.byName('IR3')
        note = Note(mw.col, model)

        def fields():
            for field in mw.col.models.fieldNames(model):
                if field == 'Text':
                    yield clipping.content
                elif field == 'Title':
                    yield '{kind} from {document}{page}{location} added {added}'.format(
                        kind=clipping.kind,
                        document=clipping.document,
                        page=' page ' + clipping.page if clipping.page is not None else '',
                        location=' location ' + clipping.location if clipping.location is not None else '',
                        added=clipping.added,
                    )
                elif field == 'Source':
                    yield '{kind} from {document}{page}{location}'.format(
                        kind=clipping.kind,
                        document=clipping.document,
                        page=' page ' + clipping.page if clipping.page is not None else '',
                        location=' location ' + clipping.location if clipping.location is not None else '',
                    )
                else:
                    raise ValueError('Unknown field: ' + field)

        note.fields = list(fields())
        mw.col.addNote(note)
        notes_added += 1

    showInfo(f'{notes_added} notes imported')


Clipping = namedtuple('Clipping', ('kind', 'document', 'page', 'location', 'added', 'content'))


CLIPPING_PATTERN = r'''\ufeff?(?P<document>.*)
- Your (?P<kind>.*) on (?:page (?P<page>.*) \| )?(?:Location (?P<location>.*) \| )?Added on (?P<added>.*)

(?P<content>.*)
?'''


def parse_clipping(string):
    match = re.fullmatch(CLIPPING_PATTERN, string)
    if not match:
        return None
    return Clipping(**match.groupdict())


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


def SimpleImporter(NoteImporter):
    def __init__(self, foreign_notes, model):
        super().__init__(col=None, file=None)
        self.model = model
        self._foreign_notes = foreign_notes

    def foreignNotes(self):
        return self._foreign_notes


main()
