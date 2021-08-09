# This module does some preprocessing.
# It identifies "candidate" pages that contain Rotten Tomatoes rating info,
# finds the corresponding Rotten Tomatoes data if possible,
# and also finds (or at least tries to) the start of the sentence in which
# the rating info is contained.
################################################################################
import regex as re
import sys
import webbrowser
import time
import string
import multiprocessing
import urllib.error # for googlesearch maybe
import logging
logger = logging.getLogger(__name__)

print_logger = logging.getLogger('print_logger')

from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from itertools import chain
from collections import defaultdict, namedtuple

import requests
import pywikibot as pwb
import wikitextparser as wtp

from pywikibot.xmlreader import XmlDump
from googlesearch import lucky

import scraper
from scraper import RTMovie, ROTTENTOMATOES_LOCK
from patterns import *
from findspan import _find_span333,_find_span222,_find_span
################################################################################
WIKIDATA_LOCK = multiprocessing.Lock()
GOOGLESEARCH_LOCK = multiprocessing.Lock()

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
    if ROTTENTOMATOES_LOCK.locked():
        sys.exit()

    title, text = entry.title, entry.text

    print_logger.info(f"Processing [[{title}]].")

    # Get allowed refnames. Dictionary maps refname to match object of the citation definition
    refnames = dict()
    for m in re.finditer(fr'<ref +name *= *"?(?P<refname>[^>]+?)"? *>((?!<ref).)*{t_alternates}((?!<ref).)*</ref *>', text, re.DOTALL):
        refnames[m['refname']] = m

    rtref_re = citation_re
    if refnames:
        allowed_refname = alternates(map(re.escape, refnames))
        ldref_re = fr'(?P<ldref><ref +name *= *"?(?P<ldrefname>{allowed_refname})"? */>)'
        rtref_re = alternates([citation_re,ldref_re])
    rtref_re = fr'\s*{rtref_re}'

    #notinref = r'(?!((?!<ref).)*</ref)'
    notincom = r'(?!((?!<!--).)*-->)'
    notinreforcom = r'(?!((?!<ref).)*</ref)(?!((?!<!--).)*-->)'
    #cand_re1 = fr'{rt_re}{notinref}{notincom}((?!</?ref|\n[\n*]|==).)*?{score_re}((?!\n\n|==).)*?(?P<refs>{anyrefs_re}{rtref_re}{anyrefs_re})'
    #cand_re2 = fr'{score_re}{notinref}{notincom}((?!</?ref|\n[\n*]|==).)*?{rt_re}((?!\n\n|==).)*?(?P<refs>{anyrefs_re}{rtref_re}{anyrefs_re})'
    #cand_re3 = fr'{t_rtprose}{notincom}((?!</?ref|\n\n|==).)*?(?P<refs>{rtref_re})'
    final_re = fr'(?:(?:({rt_re})|{score_re}){notinreforcom}((?!</?ref|\n\n|==).)*?(?(1){score_re}|{rt_re})|{t_rtprose}){notincom}((?!\n\n|==).)*?(?P<refs>{anyrefs_re}{rtref_re}{anyrefs_re})'

    rtmatch_and_initialids, id_set, previous_end = [], set(), -333
    for m in re.finditer(final_re, text, flags=re.DOTALL):
        if _inside_table_or_template(m):
            continue
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

    for rtmatch, initial in rtmatch_and_initialids:
        rtmatch.movie = _find_RTMovie(entry, initial, len(id_set)<2)
        # print(rtmatch.movie)

    if rtmatch_and_initialids:
        return Candidate(title, text, matches=rtmatch_and_initialids)
    else:
        return None


def find_candidates(xmlfile, get_user_input = False):
    """
    Given an XmlDump, yields all pages (as a Candidate) in the dump
    which match at least one pattern in patterns.
    """
    # if we get blocked (status code 403), acquire the lock
    # to let other threads know
    total, count = 0, 0
    print_logger.info(f"Found {count} candidates out of {total} pages")
    xml_entries = XmlDump(xmlfile).parse()


    return_list = list()
    # 15 threads is fine, but don't rerun on the same pages immediately
    # after a run, or the caching may result in sending too many
    # requests too fast, and we'll get blocked.
    def init(lock1, lock2, lock3):
        global WIKIDATA_LOCK
        global GOOGLESEARCH_LOCK
        global ROTTENTOMATOES_LOCK
        WIKIDATA_LOCK, GOOGLESEARCH_LOCK, ROTTENTOMATOES_LOCK = lock1, lock2, lock3

    with ThreadPoolExecutor(max_workers=16,
            init, (WIKIDATA_LOCK,GOOGLESEARCH_LOCK,ROTTENTOMATOES_LOCK) ) as x:
        futures = {x.submit(candidate_from_entry, e) : e.title for e in xml_entries}
        for future in as_completed(futures):
            total += 1
            try:
                cand = future.result()
            except Exception as e:
                x.shutdown(wait=True, cancel_futures=True)
                logger.exception("Exiting program.")
                sys.exit()
            if cand:
                if get_user_input:
                    _process_needs_input_movies(cand)
                count += 1
                #print_logger.info(f"Processed [[{futures[future]}]].")
                yield cand

    logger.info(f"Found {count} candidates out of {total} pages")
    print_logger.info(f"Found {count} candidates out of {total} pages")

def _process_needs_input_movies(cand):
    for rtm in cand.matches:
        if not rtm.movie:
            while True:
                newid = _ask_for_id(cand, rtm)
                if not newid or rtmatch._load_rt_data(newid, cand):
                    break
                print(f"Problem getting Rotten Tomatoes data with id {newid}\n")


def _ask_for_id(cand, rtmatch):
    """
    Asks for a user decision regarding the Rotten Tomatoes id for a film.
    """
    logger.debug(f"Asking for id for [[{cand.title}]]")
    title, text = cand.title, cand.text
    i, j = rtmatch.span[0], rtmatch.span[1]
    warning = ''
    if cand.multiple_movies:
        warning = 'WARNING: More than one movie url detected in this article.\n'
    prompt = f"""\033[96mNo working id found for a match in [[{title}]].\033[0m
\033[93m{warning}Context------------------------------------------------------------------------\033[0m
{text[i-60: i]}\033[1m{text[i: j]}\033[0m{text[j: j+50]}
\033[93m-------------------------------------------------------------------------------\033[0m
Please select an option:
1) enter id
2) open [[{title}]] in the browser
3) skip this candidate
4) quit the program"""
    print(prompt)
    while (user_input:=input("Your selection: ")) not in ('1','3','4'):
        if user_input == '2':
            webbrowser.open(pwb.Page(pwb.Site('en', 'wikipedia'), title).full_url())
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
        print_logger.info("Quitting program.")
        sys.exit()                

# ===========================================================================================
def _find_citation_and_id(title, m, refnames):
    if ldrefname := m.groupdict().get('ldrefname'):
        m = refnames[ldrefname]
        ref = Reference(text=m[0], name=ldrefname, list_defined=True)
    else:
        ref = Reference(m['citation'], m['refname'])

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
    page = pwb.Page(pwb.Site('en','wikipedia'), title)
    item = pwb.ItemPage.fromPage(page)
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
    # if text[span[0]:para_end].count('{{') != text[span[0]:para_end].count('}}'):
    #     return True
    # if text[para_start:para_end].count('{{') != text[para_start:para_end].count('}}'):
    #     return True
    wt = wtp.parse(text[para_start:para_end])
    for t in wt.templates:
        if t.span[0]+para_start <= span[0] and span[1] <= t.span[1]+para_start:
            return True
        elif span[1] <= t.span[0]+para_start:
            break
    return False

def googled_id(title):
    GOOGLESEARCH_LOCK.acquire()
    #time.sleep(1)       # help avoid getting blocked, better safe than sorry
    print_logger.info(f"GOOGLING ID for [[{title}]].")
    try:
        url = lucky(title + ' movie site:rottentomatoes.com/m/',
            user_agent=scraper.USER_AGENT)
    except urllib.error.HTTPError as x:
        logger.exception("Error while using googlesearch.")
        GOOGLESEARCH_LOCK.release()
        raise
    GOOGLESEARCH_LOCK.release()
    suggested_id = url.split('rottentomatoes.com/m/')[1]
    return 'm/' + suggested_id.split('/')[0]


def _find_RTMovie(page, initial_id = None, make_guess = False):
    if ROTTENTOMATOES_LOCK.locked():
        sys.exit()

    try:
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
        lead = page.text[:page.text.find('==')]
        words_to_check_for = {' ' + movie.year}
        names = chain.from_iterable(name.split() for name in movie.director+movie.writer)
        words_to_check_for.update(x for x in names if x[-1] != '.')
        if not all(x in lead for x in words_to_check_for):
            return False
        if f"'''''{movie.title}'''''" in lead:
            return True
        hrs, mins = map(int, movie.runtime[:-1].split('h '))
        runtime = 60 * hrs * mins
        if f"''{movie.title}''" in lead and f"{runtime} minutes" in lead:
            return True
        return False

    movieid = None
    for section in wtp.parse(page.text).sections[-3:]:
        if re.search(r'[eE]xternal [lL]inks', section.title):
            l = list(re.finditer(url_re, section.string))
            if len(l) == 1:
                movieid = l[0]['rt_id']
            break
    if movieid not in (initial_id, p):
        try:
            movie = RTMovie(movieid)
            if probably_correct():
                return movie
        except Exception:
            pass
    try:
        movie = RTMovie(googled_id(page.title))
        if probably_correct():
            return movie
    except Exception:
        pass
    return None


if __name__ == "__main__":
    pass




