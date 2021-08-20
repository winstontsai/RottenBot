# This module does some preprocessing.
# It identifies "candidate" pages that contain Rotten Tomatoes rating info,
# finds the corresponding Rotten Tomatoes data if possible,
# and also finds (or at least tries to) the start of the sentence in which
# the rating info is contained.
################################################################################
import sys
import webbrowser
import time
import string
import multiprocessing
import urllib.error # for googlesearch maybe
import logging
logger = logging.getLogger(__name__)

print_logger = logging.getLogger('print_logger')

from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from itertools import chain
from collections import defaultdict, namedtuple

import requests
import pywikibot as pwb
import wikitextparser as wtp
import regex as re
import colorama
colorama.init()

from pywikibot import Page, Site, ItemPage
from pywikibot.xmlreader import XmlDump
from googlesearch import lucky

import scraper
from scraper import RTMovie
from patterns import *
################################################################################


class OverlappingMatchError(Exception):
    pass

Entry = namedtuple('Entry', ['title', 'text'])

@dataclass
class Reference:
    text: str
    name: str = None
    list_defined: bool = False # i.e. defined elsewhere

@dataclass
class RTMatch:
    """
    For use in Candidate class. Represents location in an article
    with Rotten tomatoes prose that may need editing.
    """
    span: tuple[int, int]
    ref: Reference
    movie: RTMovie = None

@dataclass
class Candidate:
    """
    An instance of this class should contain all the information necessary
    to make the right edits to Rotten Tomatoes prose (while being as
    concise as possible).
    """
    title: str           # article title
    text: str            # wikitext
    matches: list[RTMatch] = field(default_factory=list)


def candidate_from_entry(entry):
    title, text = entry.title, entry.text

    print_logger.info(f"Processing [[{title}]].")

    # Get allowed refnames. Dictionary maps refname to match object of the citation definition
    refnames = dict()
    for m in re.finditer(fr'<ref +name *= *"?(?P<refname>[^>]+?)"? *>((?!<ref).)*{t_alternates}((?!<ref).)*</ref *>', text, re.DOTALL):
        refnames[m['refname']] = m

    rtref_re = citation_re
    if refnames:
        allowed_refname = alternates(map(re.escape, refnames))
        ldref_re = fr'(?P<ldref><ref +name *= *"?(?P<ldrefname>{allowed_refname})"? */>|{{{{ *[rR] *\| *(?P<ldrefname>{allowed_refname}) *}}}})'
        rtref_re = alternates([citation_re,ldref_re])
    rtref_re = fr'(?P<rtref>\s*{rtref_re})'

    #notinref = r'(?!((?!<ref).)*</ref)'
    notincom = r'(?!((?!<!--).)*-->)'
    notinreforcom = r'(?!((?!<ref).)*</ref)(?!((?!<!--).)*-->)'
    notintemplate = r'(?![^{{]*}})'
    #cand_re1 = fr'{rt_re}{notinref}{notincom}((?!</?ref|\n[\n*]|==).)*?{score_re}((?!\n\n|==).)*?(?P<refs>{anyrefs_re}{rtref_re}{anyrefs_re})'
    #cand_re2 = fr'{score_re}{notinref}{notincom}((?!</?ref|\n[\n*]|==).)*?{rt_re}((?!\n\n|==).)*?(?P<refs>{anyrefs_re}{rtref_re}{anyrefs_re})'
    #cand_re3 = fr'{t_rtprose}{notincom}((?!</?ref|\n\n|==).)*?(?P<refs>{rtref_re})'
    final_re = fr'(?:(?:({rt_re})(?![^{{]*}})|{score_re}){notinreforcom}((?!</?ref|\n\n|==).)*?(?(1){score_re}|{rt_re}(?![^{{]*}}))|{t_rtprose}){notincom}(?:((?!\n\n|==).)*?(?P<refs>{anyrefs_re}{rtref_re}{anyrefs_re}))?'

    banned_sections = []
    for sec in wtp.parse(text).get_sections(include_subsections=False):
        if re.search('(external links|references|see also|notes)', str(sec.title), re.IGNORECASE):
            banned_sections.append(sec.span)

    rtmatch_and_initialids, id_set, previous_end = [], set(), -333
    for m in re.finditer(final_re, text, flags=re.DOTALL):
        if any(is_subspan(m.span(), y) for y in banned_sections):
            continue
        if _inside_table_or_template(m):
            continue

        # if m['rtref']:
        #     continue

        if m['rtprose']:
            span = m.span()
        else:
            span = _find_span333(m, title)

        if span[0] < previous_end:
            continue
        previous_end = span[1]

        ref, initial_rt_id = _find_citation_and_id(title, m, refnames)
        id_set.add(initial_rt_id)
        rtmatch_and_initialids.append( (RTMatch(span, ref), initial_rt_id) )

    cand = Candidate(title, text)
    for rtmatch, initial in rtmatch_and_initialids:
        safe_to_guess = len(id_set)<2 or rtmatch.span[0]<text.index('\n==')
        rtmatch.movie = None#_find_RTMovie(entry, initial, safe_to_guess)
        cand.matches.append(rtmatch)

    if cand.matches:
        return cand
    else:
        return None


def _init(lock1, lock2):
    """
    To be used with Executor in find_candidates.
    """
    global WIKIDATA_LOCK
    global GOOGLESEARCH_LOCK
    WIKIDATA_LOCK, GOOGLESEARCH_LOCK = lock1, lock2

def find_candidates(xmlfile, get_user_input = False):
    """
    Given an XmlDump, yields all pages (as a Candidate) in the dump
    which match at least one pattern in patterns.
    """
    # if we get blocked (status code 403), acquire the lock
    # to let other threads know
    total, count = 0, 0
    xml_entries = XmlDump(xmlfile).parse()

    WIKIDATA_LOCK = multiprocessing.Lock()
    GOOGLESEARCH_LOCK = multiprocessing.Lock()
    with ProcessPoolExecutor(max_workers=16,
            initializer=_init,
            initargs=(WIKIDATA_LOCK,GOOGLESEARCH_LOCK) ) as x:
        futures = {x.submit(candidate_from_entry, e) : e.title for e in xml_entries}
        for future in as_completed(futures):
            total += 1
            try:
                cand = future.result()
            except Exception as e:
                x.shutdown(wait=True, cancel_futures=True)
                logger.exception("Exiting program.")
                sys.exit()
            if not cand:
                continue
            if get_user_input:
                _process_needs_input_movies(cand)
            print_logger.info(f"Found candidate [[{futures[future]}]].")
            count += 1
            yield cand

    logger.info(f"Found {count} candidates out of {total} pages")
    print_logger.info(f"Found {count} candidates out of {total} pages")

def _process_needs_input_movies(cand):
    for rtm in cand.matches:
        if rtm.movie:
            continue
        while True:
            newid = _ask_for_id(cand, rtm)
            if not newid:
                break
            if z := _find_RTMovie(cand, newid):
                rtm.movie = z
                break
            print(f"Problem getting Rotten Tomatoes data with id {newid}.\n")


def _ask_for_id(cand, rtmatch):
    """
    Asks for a user decision regarding the Rotten Tomatoes id for a film.
    """
    logger.debug(f"Asking for id for [[{cand.title}]]")
    title, text = cand.title, cand.text
    i, j = rtmatch.span[0], rtmatch.span[1]
    pspan = paragraph_span((i,j), text)
    prompt = f"""\033[96mNo working id found for a match in [[{title}]].\033[0m
\033[93mContext------------------------------------------\033[0m
{text[pspan[0]: i]}\033[1m{text[i: j]}\033[0m{text[j: pspan[1]]}
\033[93m-------------------------------------------------\033[0m
Please select an option:
1) enter id
2) open [[{title}]] in the browser
3) skip this candidate
4) quit the program"""
    print(prompt)
    while (user_input:=input("Your selection: ")) not in ('1','3','4'):
        if user_input == '2':
            webbrowser.open(Page(Site('en','wikipedia'), title).full_url())
        else:
            print("Not a valid selection.")

    print()
    if user_input == '1':
        while not (newid := input("Enter id here: ")).startswith('m/'):
            print('A valid id must begin with "m/".')
        logger.info(f"Entered id '{newid}' for [[{title}]]")
        return newid
    elif user_input == '3':
        logger.info(f"Skipping article [[{title}]]")
        return None
    elif user_input == '4':
        print("Quitting program.")
        sys.exit()                

# ===========================================================================================
def _find_span333(match, title):
    matchstart = match.start()
    para_start, para_end = paragraph_span(match.span(), match.string)

    wikitext = wtp.parse(match.string[para_start:para_end])
    # reversed to avoid possible edge cases
    for x in reversed(wikitext.get_bolds_and_italics(recursive=False)):
        x.string = len(x.string) * "'"
    for x in reversed(wikitext.wikilinks):
        x.string = len(x.string) * ']'
    for x in reversed(wikitext.external_links):
        x.string = len(x.string) * ']'
    for x in reversed(wikitext.templates):
        x.string = len(x.string) * '}'
    for x in reversed(wikitext.comments):
        x.string = len(x.string) * '`'
    for x in reversed(wikitext.get_tags()):
        x.string = len(x.string) * '@'

    text = str(wikitext).translate(str.maketrans('“”‘’','""\'\''))
    text = re.sub(r"(?<!')'(?!')", ' ', text)

    brackets_re = r'\s+\([^()]+?\)$'
    title = re.sub(brackets_re, '', title)
    rep = 'T' + 't'*(len(title)-1)
    text = re.sub(re.escape(title), rep, text)
    #print(text)
    text = match.string[:para_start] + text + match.string[para_end:]
    text = text[:match.start()] + text[match.start():para_end].replace('\n',' ') + text[para_end:]

    # TODO ' *' vs '\s*'
    p2 = re.compile(r'([.!] ?"|(?<=[^A-Z])[.!])(( *[@`]+)+|(?= +[^a-z]|\n))')
    p3 = re.compile(r'}} *@')
    i, potential_starts = matchstart, [matchstart]
    while i > para_start:
        #print(text[i:i+7])
        if text[i] in ' `@':
            i -=1; continue

        if text[i] in '\n':
            i = potential_starts[-1]
            break

        if (m:=p2.match(text, i)) or (m:=p3.match(text, i)):
            i = next(j for j in reversed(potential_starts) if j >= m.end())
            break
        potential_starts.append(i)
        i -= 1

    if match['refs']:
        search_start = rfind_pattern(r'\w', text, 0, match.start('refs'))
    else:
        search_start = rfind_pattern(r'\w', text, 0, match.end())

    if m := p2.search(text, search_start):
        j = min(m.end(), para_end)
    else:
        j = para_end

    #print(match.string[i:j])
    return (i, j)


def _find_citation_and_id(title, m, refnames):
    if ldrefname := m.groupdict().get('ldrefname'):
        m = refnames[ldrefname]
        ref = Reference(text=m[0], name=ldrefname, list_defined=True)
    elif m['citation']:
        ref = Reference(m['citation'], m['refname'])
    else:
        return None, None

    if x := m['rt_id']:
        movieid = x
    elif citert := m['citert']:
        movieid = "m/" + parse_template(citert)[1]['id']
    elif rt := m['rt']:
        d = parse_template(rt)[1]
        if '1' in d:
            movieid = ['m/',''][d['1'].startswith('m/')] + d['1']
        elif 'id' in d:
            movieid = ['m/',''][d['id'].startswith('m/')] + d['id']
        else:
            movieid = _p1258(title)
    return ref, movieid.lower()

def _p1258(title):
    WIKIDATA_LOCK.acquire()
    time.sleep(1)       # avoid getting blocked, better safe than sorry
    item = ItemPage.fromPage(Page(Site('en','wikipedia'), title))
    item.get()
    WIKIDATA_LOCK.release()
    if 'P1258' in item.claims:
        return item.claims['P1258'][0].getTarget()
    return None

def _inside_table_or_template(match):
    """
    Return True if index i of the string s is likely part of a table or template.
    Not all tables end with '{|' and '|}'. Some use templates for the start/end.
    So this function is what I came up with as a comrpomise between simplicity
    and accuracy.
    """
    span, text = match.span(), match.string
    para_start, para_end = paragraph_span(span, text)
    if '|-' in text[para_start:para_end]:
        return True
    wt = wtp.parse(text[para_start:para_end])
    for t in wt.templates:
        if is_subspan(span, (t.span[0]+para_start, t.span[1]+para_start) ):
            return True
        elif span[1] <= t.span[0]+para_start:
            break
    return False

def googled_id(title):
    GOOGLESEARCH_LOCK.acquire()
    time.sleep(1)       # avoid getting blocked, better safe than sorry
    print_logger.info(f"GOOGLING ID for [[{title}]].")
    try:
        url = lucky(title+' movie site:rottentomatoes.com/m/',user_agent=scraper.USER_AGENT)
    except urllib.error.HTTPError as x:
        GOOGLESEARCH_LOCK.release()
        raise
    else:
        GOOGLESEARCH_LOCK.release()
    suggested_id = url.split('rottentomatoes.com/m/')[1]
    return 'm/' + suggested_id.split('/')[0]


def _find_RTMovie(page, initial_id, make_guess = False):
    try:
        if initial_id:
            return RTMovie(initial_id)
    except Exception:
        pass

    if not make_guess:
        return None

    if (p := _p1258(page.title)) and p != initial_id:
        try:
            return RTMovie(p)
        except Exception:
            pass

    def probably_correct():
        lead = page.text[:page.text.index('\n==')]
        words_to_check_for = {' ' + movie.year}
        names = chain.from_iterable(name.split() for name in movie.director+movie.writer)
        words_to_check_for.update(x for x in names if x[-1] != '.')
        if not all(x in lead for x in words_to_check_for):
            return False
        if f"''{movie.title}''" in lead:
            return True
        return False

    try:
        movie = RTMovie(googled_id(page.title))
    except Exception:
        pass
    else:
        if probably_correct():
            return movie
    return None


if __name__ == "__main__":
    pass




