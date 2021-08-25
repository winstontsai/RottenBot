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

from concurrent.futures import ProcessPoolExecutor, as_completed, ThreadPoolExecutor
from dataclasses import dataclass, field
from itertools import chain
from collections import defaultdict, namedtuple

import requests
import pywikibot as pwb
import wikitextparser as wtp
import regex as re

from pywikibot import Page, Site, ItemPage
from pywikibot.xmlreader import XmlDump
from googlesearch import lucky
from colorama import Fore, Style

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
    total, count = 0, 0
    xml_entries = XmlDump(xmlfile).parse()

    WIKIDATA_LOCK = multiprocessing.Lock()
    GOOGLESEARCH_LOCK = multiprocessing.Lock()
    with ProcessPoolExecutor(max_workers=16,
            initializer=_init, initargs=(WIKIDATA_LOCK,GOOGLESEARCH_LOCK) ) as x:
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


def candidate_from_entry(entry):
    title, text = entry.title, entry.text
    # Get allowed refnames.
    # Dictionary maps refname to match object of the citation definition.
    refnames = dict()
    for m in re.finditer(fr'<ref +name *= *"?(?P<refname>[^>]+?)"? *>((?!<ref).)*{t_alternates}((?!<ref).)*</ref *>', text, re.S):
        refnames[m['refname']] = m

    rtref_re = citation_re
    if refnames:
        allowed_refname = alternates(map(re.escape, refnames))
        ldref_re = fr'<ref +name *= *"?(?P<ldrefname>{allowed_refname})"? */>|{{{{ *[rR] *\| *(?P<ldrefname>{allowed_refname}) *}}}}'
        rtref_re = alternates([citation_re,ldref_re])
    rtref_re = fr'\s*{rtref_re}'
    
    final_re = fr'{template_re}(?:{t_rtprose}|(?:{rt_re+notincurly}|{score_re}){notinref+notincom}((?!</?ref|\n\n|==).)*?(?(rot){score_re}|{rt_re+notincurly})){notincom+notinbadsection}(?:((?!\n\n|==).)*?(?P<refs>{anyrefs_re}{rtref_re}{anyrefs_re}))?'

    rtmatch_and_initialids, id_set, previous_end = [], set(), -333
    for m in re.finditer(final_re, text, flags=re.S):
        #print(m)

        # if _inside_table(m):
        #     continue

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
        rtmatch.movie = _find_RTMovie(entry, initial, safe_to_guess)
        cand.matches.append(rtmatch)

    if cand.matches:
        return cand

def _process_needs_input_movies(cand):
    for rtm in cand.matches:
        if rtm.movie:
            continue
        while True:
            newid = _ask_for_id(cand, rtm)
            if newid is None:
                break
            if z := _find_RTMovie(cand, newid):
                rtm.movie = z
                break
            print(f"Problem getting Rotten Tomatoes data with id {newid}.\n")


def _ask_for_id(cand, rtmatch):
    """
    Asks for a user decision regarding the Rotten Tomatoes id for a film.
    """
    title, text = cand.title, cand.text
    i, j = rtmatch.span[0], rtmatch.span[1]
    pspan = paragraph_span((i,j), text)
    prompt = f"""{Fore.CYAN+Style.BRIGHT}Need id for a match in [[{title}]].{Style.RESET_ALL}
{Fore.GREEN+Style.BRIGHT}Context------------------------------------------{Style.RESET_ALL}
{text[pspan[0]: i] + Style.BRIGHT + text[i: j] + Style.RESET_ALL + text[j: pspan[1]]}
{Fore.GREEN+Style.BRIGHT}-------------------------------------------------{Style.RESET_ALL}
"""
    print(prompt)
    while not re.fullmatch(r'm/[-a-z0-9_]+',
        (user_input:=input("Enter id (or open in [b]rowser, [s]kip, or [q]uit): "))):
        if user_input == 'b':
            webbrowser.open(Page(Site('en','wikipedia'), title).full_url())
        elif user_input == 's':
            print(f"Skipping match."); return None
        elif user_input == 'q':
            print("Quitting program."); sys.exit()
        else:
            print("Invalid id. Must begin with 'm/', e.g. 'm/titanic'.")

# ===========================================================================================
def _find_span333(match, title):
    if match['refs'] and match['rtprose']:
        return match.span()

    matchstart = match.start()
    para_start, para_end = paragraph_span(match.span(), match.string)

    wikitext = wtp.parse(match.string[para_start:para_end])
    # reversed to avoid possible edge cases
    for x in reversed(wikitext.get_bolds_and_italics(recursive=False)):
        x.string = len(x.string) * "'"
    for x in reversed(wikitext.wikilinks):
        x.string = '[[' + (len(x.string)-4)*'a' + ']]'
    for x in reversed(wikitext.external_links):
        x.string = '[' + (len(x.string)-2)*'a' + ']'
    for x in reversed(wikitext.templates):
        x.string = '{{' + (len(x.string)-4)*'a' + '}}'
    for x in reversed(wikitext.comments):
        x.string = len(x.string) * '`'
    for x in reversed(wikitext.get_tags()):
        x.string = len(x.string) * '@'

    text = str(wikitext).translate(str.maketrans('“”‘’','""\'\''))
    #text = re.sub(r"(?<!')'(?!')", ' ', text)

    brackets_re = r'\s+\([^()]+?\)$'
    title = re.sub(brackets_re, '', title)
    rep = 'T' + 't'*(len(title)-1)
    text = re.sub(re.escape(title), rep, text)
    
    text = match.string[:para_start] + text + match.string[para_end:]
    #text = text[:matchstart] + text[matchstart: para_end].replace('\n',' ') + text[para_end:]

    p4 = re.compile(r'(?:([.!][ \']?"|(?<![A-Z])[.!])((\s*[@`]+)+|(?=\s+[^a-z]))|}}\s*@+|\n)\s*', flags=re.REVERSE)
    i = p4.search(text, 0, matchstart+1).end()

    p5 = re.compile(r'([.!][ \']?"|(?<![A-Z])[.!])((\s*[@`]+)+|(?=\s+[^a-z]))|}}\s*@+|(?=\n\n|\n==)')
    j = p5.search(text, pos=rindex_pattern(r'\w', text, 0, match.end())).end()

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

def _inside_table(match):
    """
    Return True if index i of the string s is likely part of a table or template.
    Not all tables end with '{|' and '|}'. Some use templates for the start/end.
    So this function is what I came up with as a comrpomise between simplicity
    and accuracy.
    """
    span, text = match.span(), match.string
    pstart, pend = paragraph_span(span, text)
    if '|-' in text[pstart:pend]:
        return True
    return False

def googled_id(title):
    GOOGLESEARCH_LOCK.acquire()
    time.sleep(1)       # avoid getting blocked, better safe than sorry
    print_logger.info(f"GOOGLING ID for [[{title}]].")
    try:
        url = lucky(title+' movie site:rottentomatoes.com/m/',
            user_agent=scraper.USER_AGENT)
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
        names = chain.from_iterable(name.split() for name in movie.director+movie.writer)
        checkwords = [x for x in names if x[-1] != '.']+[' '+movie.year]
        if any(x not in lead for x in checkwords):
            return False
        if f"'''''{movie.title}'''''" in lead:
            return True
        if not f"''{movie.title}''" in lead:
            return False
        z = re.findall(r'\d+', movie.runtime)
        if len(z) == 1:
            minutes = int(z[0])
        else:
            hours, minutes = map(int, z)
        return f'{60*hours + minutes} minutes' in lead

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


