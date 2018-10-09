from datetime import datetime
import re
from collections import namedtuple

from bs4 import BeautifulSoup

from anki.notes import Note
from anki.utils import splitFields, stripHTMLMedia
from aqt import mw
from aqt.utils import getFile, showInfo, showText
from aqt.qt import QAction


def main():
    action = QAction('Import Kindle highlights...', mw)
    action.triggered.connect(import_highlights)
    mw.form.menuTools.addAction(action)


def import_highlights():
    path = getFile(mw, 'Open Kindle clippings', cb=None, filter='Clippings file (*.txt *.html)', key='KindleHighlights')

    with open(path, encoding='utf-8') as file:
        lower_path = path.lower()
        if lower_path.endswith('txt'):
            clippings, bad_clippings = parse_text_clippings(file)
        elif lower_path.endswith('html'):
            clippings, bad_clippings = parse_html_clippings(file)
        else:
            raise RuntimeError(f'Unknown extension in path: {path!r}')

    if bad_clippings:
        showText(
            f'The following {len(bad_clippings)} clippings could not be parsed:\n\n' +
            '\n==========\n'.join(bad_clippings))

    config = mw.addonManager.getConfig(__name__)

    highlight_clippings = list(highlights_only(clippings))
    clippings_to_add = after_last_added(highlight_clippings, last_added_datetime(config))

    num_added = 0
    last_added = None

    note_adder = NoteAdder(mw.col, config)
    for clipping in clippings_to_add:
        note_was_added = note_adder.try_add(clipping)
        if note_was_added:
            num_added += 1
            if clipping.added:
                last_added = clipping.added

    if last_added:
        config['last_added'] = parse_clipping_added(last_added).isoformat()
        mw.addonManager.writeConfig(__name__, config)

    def info():
        if num_added:
            yield f'{num_added} new highlights imported'

        num_duplicates = len(clippings_to_add) - num_added
        if num_duplicates:
            yield f'{num_duplicates} duplicate highlights ignored'

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


def parse_text_clippings(file):
    clippings = []
    bad_clippings = []

    current_clipping_lines = []
    for line in file:
        if line != '==========\n':
            current_clipping_lines.append(line)
            continue

        string = ''.join(current_clipping_lines)
        current_clipping_lines.clear()

        clipping = parse_text_clipping(string)

        if clipping:
            clippings.append(clipping)
        else:
            bad_clippings.append(string)

    if current_clipping_lines:
        bad_clippings.append(''.join(current_clipping_lines))

    return clippings, bad_clippings


def parse_text_clipping(string):
    match = re.fullmatch(CLIPPING_PATTERN, string)
    if not match:
        return None
    return Clipping(**match.groupdict())


CLIPPING_PATTERN = r'''\ufeff?(?P<document>.*)
- Your (?P<kind>.*) on (?:page (?P<page>.*) \| )?(?:Location (?P<location>.*) \| )?Added on (?P<added>.*)

(?P<content>.*)
?'''


def parse_html_clippings(file):
    clippings = []
    bad_clippings = []

    soup = BeautifulSoup(file, 'html.parser')

    title = None
    authors = None
    section = None
    kind = None
    subsection = None
    location = None

    for paragraph in soup.find_all(class_=True):
        classes = paragraph['class']
        text = paragraph.get_text().strip()

        if 'bookTitle' in classes:
            title = text

        if  'authors' in classes:
            authors = text

        if 'sectionHeading' in classes:
            section = text

        if 'noteHeading' in classes:
            match = re.fullmatch(NOTE_HEADING_PATTERN, text)
            if not match:
                bad_clippings.append(text)
                kind = None
                location = None
                subsection = None
            else:
                kind = match['kind'].strip()
                location = match['location'].strip()
                if match['subsection']:
                    subsection = match['subsection'].strip()
                else:
                    subsection = None

        if 'noteText' in classes:
            content = text
        else:
            continue

        if not kind or not location:
            bad_clippings.append(text)
            continue

        if title and authors:
            document = f'{title} ({authors})'
        elif title:
            document = title
        elif authors:
            document = authors

        if section:
            document += ' ' + section + ','

        if subsection:
            document += ' ' + subsection + ','

        clippings.append(Clipping(
            kind=kind,
            document=document,
            page=None,
            location=location,
            added=None,
            content=content,
        ))

    return clippings, bad_clippings


NOTE_HEADING_PATTERN = r'(?P<kind>.*)\s*-\s*(?:(?P<subsection>.*)\s*>\s*)?Location\s*(?P<location>.*)'


def after_last_added(clippings, last_added):
    if not last_added:
        return clippings

    def reversed_clippings_after_last_added():
        for clipping in reversed(clippings):
            if clipping.added:
                clipping_added = parse_clipping_added(clipping.added)
                if clipping_added and clipping_added <= last_added:
                    return
            yield clipping

    clippings_after_last_added = list(reversed_clippings_after_last_added())
    clippings_after_last_added.reverse()
    return clippings_after_last_added


def parse_clipping_added(clipping_added):
    return datetime.strptime(clipping_added, '%A, %B %d, %Y %I:%M:%S %p')


def last_added_datetime(config):
    last_added_config = config['last_added']
    return datetime.strptime(last_added_config, '%Y-%m-%dT%H:%M:%S') if last_added_config else None


def highlights_only(clippings):
    for clipping in clippings:
        if 'highlight' in clipping.kind.lower():
            yield clipping


class NoteAdder:
    def __init__(self, collection, config):
        self.collection = collection
        self.model = self.collection.models.byName(config['model_name'])
        self._find_field_indexes(config)

        note_fields = self.collection.db.all(
                'select flds from notes where mid = ?', self.model['id'])
        self.present_normalized_contents = {
            normalized_content(splitFields(fields)[self.content_field_index])
            for fields, in note_fields
        }

    def _find_field_indexes(self, config):
        self.content_field_index = None
        self.source_field_index = None

        for index, field in enumerate(self.collection.models.fieldNames(self.model)):
            if field == config['content_field']:
                self.content_field_index = index
            elif field == config['source_field']:
                self.source_field_index = index

        if self.content_field_index is None or self.source_field_index is None:
            raise ValueError('Could not find content and/or source fields in model.')

    def try_add(self, clipping):
        normalized_note_content = normalized_content(note_content(clipping))
        if normalized_note_content in self.present_normalized_contents:
            return False

        note = self._note(clipping)

        self.collection.addNote(note)

        card_ids = [card.id for card in note.cards()]
        self.collection.sched.suspendCards(card_ids)

        self.present_normalized_contents.add(normalized_note_content)

        return True

    def _note(self, clipping):
        note = Note(self.collection, self.model)
        note.fields[self.content_field_index] = note_content(clipping)
        note.fields[self.source_field_index] = note_source(clipping)
        return note


def normalized_content(content):
    return stripHTMLMedia(content).strip()


def note_content(clipping):
    return clipping.content.strip()


def note_source(clipping):
    kind = clipping.kind.lower()
    document = clipping.document
    page = ' page ' + clipping.page if clipping.page is not None else ''
    location = ' location ' + clipping.location if clipping.location is not None else ''
    added = ' added ' + clipping.added if clipping.added is not None else ''
    return f'Kindle {kind} from {document}{page}{location}{added}'


main()
