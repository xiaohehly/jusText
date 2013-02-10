# -*- coding: utf8 -*-

"""
Copyright (c) 2011 Jan Pomikalek

This software is licensed as described in the file LICENSE.rst.
"""

import os
import re
import sys
import pkgutil
import lxml.etree
import lxml.html
import lxml.sax

from xml.sax.handler import ContentHandler


MAX_LINK_DENSITY_DEFAULT = 0.2
LENGTH_LOW_DEFAULT = 70
LENGTH_HIGH_DEFAULT = 200
STOPWORDS_LOW_DEFAULT = 0.30
STOPWORDS_HIGH_DEFAULT = 0.32
NO_HEADINGS_DEFAULT = False
# Short and near-good headings within MAX_HEADING_DISTANCE characters before
# a good paragraph are classified as good unless --no-headings is specified.
MAX_HEADING_DISTANCE_DEFAULT = 200
PARAGRAPH_TAGS = ['blockquote', 'caption', 'center', 'col', 'colgroup', 'dd',
        'div', 'dl', 'dt', 'fieldset', 'form', 'legend', 'optgroup', 'option',
        'p', 'pre', 'table', 'td', 'textarea', 'tfoot', 'th', 'thead', 'tr',
        'ul', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6']
DEFAULT_ENCODING = 'utf-8'
DEFAULT_ENC_ERRORS = 'replace'
CHARSET_META_TAG_PATTERN = re.compile(r"""<meta[^>]+charset=["']?([^'"/>\s]+)""",
    re.IGNORECASE)

class JustextError(Exception):
    "Base class for jusText exceptions."

class JustextInvalidOptions(JustextError):
    pass


def get_stoplists():
    """Returns a collection of built-in stop-lists."""
    path_to_stoplists = os.path.dirname(sys.modules["justext"].__file__)
    path_to_stoplists = os.path.join(path_to_stoplists, "stoplists")

    stoplist_names = []
    for filename in os.listdir(path_to_stoplists):
        name, extension = os.path.splitext(filename)
        if extension == ".txt":
            stoplist_names.append(name)

    return tuple(stoplist_names)


def get_stoplist(language):
    """Returns an built-in stop-list for the language as a set of words."""
    file_path = os.path.join("stoplists", "%s.txt" % language)
    stopwords = pkgutil.get_data("justext", file_path)

    return frozenset(w.decode("utf8") for w in stopwords.splitlines())


def decode_html(html_string, encoding=None, default_encoding=DEFAULT_ENCODING,
        errors=DEFAULT_ENC_ERRORS):
    """
    Converts a `html_string` containing an HTML page into Unicode.
    Tries to guess character encoding from meta tag.
    """
    if isinstance(html_string, unicode):
        return html_string

    if encoding:
        return html_string.decode(encoding, errors)

    match = CHARSET_META_TAG_PATTERN.search(html_string)
    if match:
        declared_encoding = match.group(1)
        try:
            return html_string.decode(declared_encoding, errors)
        except LookupError:
            # unknown encoding - proceed as if it wasn't found at all
            pass

    # unknown encoding
    try:
        # try UTF-8 first
        return html_string.decode("utf8")
    except UnicodeDecodeError:
        # try lucky with default encoding
        try:
            return html_string.decode(default_encoding)
        except UnicodeDecodeError as e:
            raise JustextError("Unable to decode the HTML to Unicode: " + str(e))


decode_entities_pp_trans = {
    ord(u'\x83'): u'\u0192',
    ord(u'\x84'): u'\u201e',
    ord(u'\x85'): u'\u2026',
    ord(u'\x86'): u'\u2020',
    ord(u'\x87'): u'\u2021',
    ord(u'\x88'): u'\u02c6',
    ord(u'\x89'): u'\u2030',
    ord(u'\x8a'): u'\u0160',
    ord(u'\x8b'): u'\u2039',
    ord(u'\x8c'): u'\u0152',
    ord(u'\x91'): u'\u2018',
    ord(u'\x92'): u'\u2019',
    ord(u'\x93'): u'\u201c',
    ord(u'\x94'): u'\u201d',
    ord(u'\x95'): u'\u2022',
    ord(u'\x96'): u'\u2013',
    ord(u'\x97'): u'\u2014',
    ord(u'\x98'): u'\u02dc',
    ord(u'\x99'): u'\u2122',
    ord(u'\x9a'): u'\u0161',
    ord(u'\x9b'): u'\u203a',
    ord(u'\x9c'): u'\u0153',
    ord(u'\x9f'): u'\u0178',
}
def decode_entities_pp(unicode_string):
    """
    Post-processing of HTML entity decoding. The entities &#128; to &#159;
    (&#x80; to &#x9f;) are not defined in HTML 4, but they are still used on
    the web and recognised by web browsers. This method converts some of the
    u'\x80' to u'\x9f' characters (which are likely to be incorrectly decoded
    entities; mostly control characters) to the characters which the entities
    are normally decoded to.
    """
    return unicode_string.translate(decode_entities_pp_trans)


def is_blank(string):
    """
    Returns `True` if string contains only white-space characters
    or is empty. Otherwise `False` is returned.
    """
    return not bool(string.lstrip())


def add_kw_tags(root):
    """
    Surrounds text nodes with <kw></kw> tags. To protect text nodes from
    being removed with nearby tags.
    """
    nodes_with_text = []
    nodes_with_tail = []
    for node in root.iter():
        # temporary workaround for issue #2 caused by a bug #690110 in lxml
        try:
            node.text
        except UnicodeDecodeError:
            # remove any text that can't be decoded
            node.text = ''

        if node.text and node.tag not in (lxml.etree.Comment, lxml.etree.ProcessingInstruction):
            nodes_with_text.append(node)
        if node.tail:
            nodes_with_tail.append(node)
    for node in nodes_with_text:
        if is_blank(node.text):
            node.text = None
        else:
            kw = lxml.etree.Element('kw')
            kw.text = node.text
            node.text = None
            node.insert(0, kw)
    for node in nodes_with_tail:
        if is_blank(node.tail):
            node.tail = None
        else:
            kw = lxml.etree.Element('kw')
            kw.text = node.tail
            node.tail = None
            parent = node.getparent()
            parent.insert(parent.index(node) + 1, kw)
    return root


def remove_comments(root):
    "Removes comment nodes."
    comments = []
    for node in root.iter():
        if isinstance(node, lxml.html.HtmlComment):
            comments.append(node)

    # start with inner most nodes
    for comment in reversed(comments):
        comment.drop_tree()


def remove_tags(root, *tags):
    useless_tags = tuple(n for n in root.iter() if n.tag in tags)
    # start with inner most nodes
    for node in reversed(useless_tags):
        node.drop_tree()


def preprocess(html_text, encoding=None, default_encoding=DEFAULT_ENCODING,
        enc_errors=DEFAULT_ENC_ERRORS):
    "Converts HTML to DOM and removes unwanted parts."
    if isinstance(html_text, unicode):
        decoded_html = html_text
        # encode HTML for case it's XML with encoding declaration
        encoding_type = encoding if encoding else default_encoding
        html_text = html_text.encode(encoding_type, enc_errors)
    else:
        decoded_html = decode_html(html_text, encoding, default_encoding, enc_errors)

    try:
        root = lxml.html.fromstring(decoded_html)
    except ValueError: # Unicode strings with encoding declaration are not supported.
        # for XHTML files with encoding declaration, use the declared encoding
        root = lxml.html.fromstring(html_text)

    # add <kw> tags, protect text nodes
    add_kw_tags(root)
    # clean DOM from useless tags
    remove_comments(root)
    remove_tags(root, "head", "script", "style")

    return root


MULTIPLE_WHITESPACE_PATTERN = re.compile(r"\s+", re.UNICODE)
def normalize_whitespace(string):
    """Translates multiple white-space into single space."""
    return MULTIPLE_WHITESPACE_PATTERN.sub(" ", string)


class SaxPragraphMaker(ContentHandler):
    """
    A class for converting a HTML page represented as a DOM object into a list
    of paragraphs.
    """

    def __init__(self):
        self.dom = []
        self.paragraphs = []
        self.paragraph = {}
        self.link = False
        self.br = False
        self._start_new_pragraph()

    def _start_new_pragraph(self):
        if self.paragraph and self.paragraph['text_nodes'] != []:
            text = ''.join(self.paragraph['text_nodes'])
            self.paragraph['text'] = normalize_whitespace(text.strip())
            self.paragraphs.append(self.paragraph)

        self.paragraph = {
            'dom_path': '.'.join(self.dom),
            'text_nodes': [],
            'word_count': 0,
            'linked_char_count': 0,
            'tag_count': 0,
        }

    def startElementNS(self, name, qname, attrs):
        dummy_uri, name = name
        self.dom.append(name)
        if name in PARAGRAPH_TAGS or (name == 'br' and self.br):
            if name == 'br':
                # the <br><br> is a paragraph separator and should
                # not be included in the number of tags within the
                # paragraph
                self.paragraph['tag_count'] -= 1
            self._start_new_pragraph()
        else:
            if name == 'br':
                self.br = True
            else:
                self.br = False
            if name == 'a':
                self.link = True
            self.paragraph['tag_count'] += 1

    def endElementNS(self, name, qname):
        dummy_uri, name = name
        self.dom.pop()
        if name in PARAGRAPH_TAGS:
            self._start_new_pragraph()
        if name == 'a':
            self.link = False

    def endDocument(self):
        self._start_new_pragraph()

    def characters(self, content):
        if content.strip() == '':
            return
        text = normalize_whitespace(content)
        self.paragraph['text_nodes'].append(text)
        words = text.strip().split()
        self.paragraph['word_count'] += len(words)
        if self.link:
            self.paragraph['linked_char_count'] += len(text)
        self.br = False

def make_paragraphs(root):
    "Converts DOM into paragraphs."
    handler = SaxPragraphMaker()
    lxml.sax.saxify(root, handler)
    return handler.paragraphs

def classify_paragraphs(paragraphs, stoplist, length_low=LENGTH_LOW_DEFAULT,
        length_high=LENGTH_HIGH_DEFAULT, stopwords_low=STOPWORDS_LOW_DEFAULT,
        stopwords_high=STOPWORDS_HIGH_DEFAULT, max_link_density=MAX_LINK_DENSITY_DEFAULT,
        no_headings=NO_HEADINGS_DEFAULT):
    "Context-free pragraph classification."
    for paragraph in paragraphs:
        length = len(paragraph['text'])
        stopword_count = 0
        for word in paragraph['text'].split():
            if word in stoplist:
                stopword_count += 1
        word_count = paragraph['word_count']
        if word_count == 0:
            stopword_density = 0
            link_density = 0
        else:
            stopword_density = 1.0 * stopword_count / word_count
            link_density = float(paragraph['linked_char_count']) / length
        paragraph['stopword_count'] = stopword_count
        paragraph['stopword_density'] = stopword_density
        paragraph['link_density'] = link_density

        paragraph['heading'] = bool(not no_headings and re.search('(^h\d|\.h\d)', paragraph['dom_path']))
        if link_density > max_link_density:
            paragraph['cfclass'] = 'bad'
        elif (u'\xa9' in paragraph['text']) or ('&copy' in paragraph['text']):
            paragraph['cfclass'] = 'bad'
        elif re.search('(^select|\.select)', paragraph['dom_path']):
            paragraph['cfclass'] = 'bad'
        else:
            if length < length_low:
                if paragraph['linked_char_count'] > 0:
                    paragraph['cfclass'] = 'bad'
                else:
                    paragraph['cfclass'] = 'short'
            else:
                if stopword_density >= stopwords_high:
                    if length > length_high:
                        paragraph['cfclass'] = 'good'
                    else:
                        paragraph['cfclass'] = 'neargood'
                elif stopword_density >= stopwords_low:
                    paragraph['cfclass'] = 'neargood'
                else:
                    paragraph['cfclass'] = 'bad'

def _get_neighbour(i, paragraphs, ignore_neargood, inc, boundary):
    while i + inc != boundary:
        i += inc
        c = paragraphs[i]['class']
        if c in ['good', 'bad']:
            return c
        if c == 'neargood' and not ignore_neargood:
            return c
    return 'bad'

def get_prev_neighbour(i, paragraphs, ignore_neargood):
    """
    Return the class of the paragraph at the top end of the short/neargood
    paragraphs block. If ignore_neargood is True, than only 'bad' or 'good'
    can be returned, otherwise 'neargood' can be returned, too.
    """
    return _get_neighbour(i, paragraphs, ignore_neargood, -1, -1)

def get_next_neighbour(i, paragraphs, ignore_neargood):
    """
    Return the class of the paragraph at the bottom end of the short/neargood
    paragraphs block. If ignore_neargood is True, than only 'bad' or 'good'
    can be returned, otherwise 'neargood' can be returned, too.
    """
    return _get_neighbour(i, paragraphs, ignore_neargood, 1, len(paragraphs))

def revise_paragraph_classification(paragraphs, max_heading_distance=MAX_HEADING_DISTANCE_DEFAULT):
    """
    Context-sensitive paragraph classification. Assumes that classify_pragraphs
    has already been called.
    """
    # copy classes
    for paragraph in paragraphs:
        paragraph['class'] = paragraph['cfclass']

    # good headings
    for i, paragraph in enumerate(paragraphs):
        if not (paragraph['heading'] and paragraph['class'] == 'short'):
            continue
        j = i + 1
        distance = 0
        while j < len(paragraphs) and distance <= max_heading_distance:
            if paragraphs[j]['class'] == 'good':
                paragraph['class'] = 'neargood'
                break
            distance += len(paragraphs[j]['text'])
            j += 1

    # classify short
    new_classes = {}
    for i, paragraph in enumerate(paragraphs):
        if paragraph['class'] != 'short':
            continue
        prev_neighbour = get_prev_neighbour(i, paragraphs, ignore_neargood=True)
        next_neighbour = get_next_neighbour(i, paragraphs, ignore_neargood=True)
        neighbours = set((prev_neighbour, next_neighbour))
        if neighbours == set(['good']):
            new_classes[i] = 'good'
        elif neighbours == set(['bad']):
            new_classes[i] = 'bad'
        # it must be set(['good', 'bad'])
        elif (prev_neighbour == 'bad' and get_prev_neighbour(i, paragraphs, ignore_neargood=False) == 'neargood') or \
             (next_neighbour == 'bad' and get_next_neighbour(i, paragraphs, ignore_neargood=False) == 'neargood'):
            new_classes[i] = 'good'
        else:
            new_classes[i] = 'bad'

    for i, c in new_classes.iteritems():
        paragraphs[i]['class'] = c

    # revise neargood
    for i, paragraph in enumerate(paragraphs):
        if paragraph['class'] != 'neargood':
            continue
        prev_neighbour = get_prev_neighbour(i, paragraphs, ignore_neargood=True)
        next_neighbour = get_next_neighbour(i, paragraphs, ignore_neargood=True)
        if (prev_neighbour, next_neighbour) == ('bad', 'bad'):
            paragraph['class'] = 'bad'
        else:
            paragraph['class'] = 'good'

    # more good headings
    for i, paragraph in enumerate(paragraphs):
        if not (paragraph['heading'] and paragraph['class'] == 'bad' and paragraph['cfclass'] != 'bad'):
            continue
        j = i + 1
        distance = 0
        while j < len(paragraphs) and distance <= max_heading_distance:
            if paragraphs[j]['class'] == 'good':
                paragraph['class'] = 'good'
                break
            distance += len(paragraphs[j]['text'])
            j += 1

def justext(html_text, stoplist, length_low=LENGTH_LOW_DEFAULT,
        length_high=LENGTH_HIGH_DEFAULT, stopwords_low=STOPWORDS_LOW_DEFAULT,
        stopwords_high=STOPWORDS_HIGH_DEFAULT, max_link_density=MAX_LINK_DENSITY_DEFAULT,
        max_heading_distance=MAX_HEADING_DISTANCE_DEFAULT, no_headings=NO_HEADINGS_DEFAULT,
        encoding=None, default_encoding=DEFAULT_ENCODING,
        enc_errors=DEFAULT_ENC_ERRORS):
    """
    Converts an HTML page into a list of classified paragraphs. Each paragraph
    is represented as a dictionary with the following attributes:

    text:
      Plain text content.

    cfclass:
      The context-free class -- class assigned by the context-free
      classification: 'good', 'bad', 'neargood' or 'short'.

    class:
      The final class: 'good' or 'bad'.

    heading:
      Set to True of the paragraph contains a heading, False otherwise.

    word_count:
      Number of words.

    linked_char_count:
      Number of characters inside links.

    link_density:
      linked_char_count / len(text)

    stopword_count:
      Number of stop-words in stop-list.

    stopword_density:
      stopword_count / word_count

    dom_path:
      A dom path to the paragraph in the original HTML page.
    """
    root = preprocess(html_text, encoding=encoding,
        default_encoding=default_encoding, enc_errors=enc_errors)
    paragraphs = make_paragraphs(root)
    classify_paragraphs(paragraphs, stoplist, length_low, length_high,
        stopwords_low, stopwords_high, max_link_density, no_headings)
    revise_paragraph_classification(paragraphs, max_heading_distance)
    return paragraphs
