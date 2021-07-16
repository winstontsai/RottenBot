# This module does some preprocessing.
# It identifies "candidate" pages that contain Rotten Tomatoes rating info,
# finds the corresponding Rotten Tomatoes data if possible,
# and also finds (or at least tries to) the start of the sentence in which
# the rating info is contained.
################################################################################
import re
import sys
import webbrowser
import time
import string
import urllib.error # for google search maybe
import logging
logger = logging.getLogger(__name__)
print_logger = logging.getLogger('print_logger')

from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from dataclasses import dataclass, field
from itertools import chain
from collections import defaultdict, namedtuple

import requests
import pywikibot as pwb

from pywikibot.xmlreader import XmlDump
from googlesearch import lucky

import scraper
from scraper import RTMovie
from patterns import *
################################################################################
WIKIDATA_LOCK = Lock()
GOOGLESEARCH_LOCK = Lock()

class OverlappingMatchError(Exception):
    pass

Entry = namedtuple('Entry',['title'])

@dataclass
class Reference:
    text: str
    name: str = None
    list_defined: bool = False

@dataclass
class RTMatch:
    """
    For use in Candidate class. Represents location in an article
    with Rotten tomatoes prose that may need editing.
    """
    span: tuple[int, int, int]
    ref: Reference
    rt_data: RTMovie = None

    def _load_rt_data(self, movieid, cand, make_guess = False):
        if scraper.BLOCKED_LOCK.locked():
            sys.exit()

        title = cand.title

        try:
            self.rt_data = RTMovie(movieid)
            return True
        except requests.exceptions.HTTPError as x:
            if x.response.status_code not in [403, 404, 500, 504]:
                raise
        except requests.exceptions.TooManyRedirects as x:
            pass

        if not make_guess:
            logger.info(f"Couldn't get RT data for [[{title}]] with id {movieid}.")
            return False

        logger.info(f"Couldn't get RT data for [[{title}]] with id {movieid}. Checking Wikidata property P1258.")
        if (p := _p1258(title)) and p != movieid:
            try:
                self.rt_data = RTMovie(p)
                return True
            except requests.exceptions.HTTPError as x:
                if x.response.status_code not in [403, 404, 500, 504]:
                    raise
            except requests.exceptions.TooManyRedirects as x:
                pass
            logger.info(f'Problem getting Rotten Tomatoes data for [[{title}]] with P1258 value {p}')
        elif not p:
            logger.info(f"[[{title}]] does not have Wikidata property P1258")

        logger.info(f"Performing lucky Google search for [[{title}]]")
        guessid = suggested_id(title)

        try:
            movie = RTMovie(guessid)
        except Exception:
            pass
        else:
            def probably_correct():
                text = cand.text
                lead = text[:text.find('==')]
                words_to_check_for = set([' ' + movie.year])
                names = chain(*(name.split() for name in movie.director+movie.writer))
                words_to_check_for.update(x for x in names if x[-1] != '.')
                if not all(x in lead for x in words_to_check_for):
                    return False
                if f"'''''{movie.title}'''''" in lead:
                    return True
                hrs, mins = movie.runtime[:-1].split('h ')
                runtime = 60 * int(hrs) + int(mins)
                if f"''{movie.title}''" in lead and f"{runtime} minutes" in lead:
                    return True
                return False

            if probably_correct():
                self.rt_data = movie
                return True

        logger.info(f"Google search for [[{title}]] failed.")
        return False

@dataclass
class Candidate:
    """
    An instance of this class should contain all the information necessary
    to make the right edits to Rotten Tomatoes prose (while being as
    concise as possible).
    """
    title: str                    # article title
    text: str                     # wikitext
    multiple_movies: bool = False # some articles have RT stuff for more than one movie, e.g. sequels
    matches: list[RTMatch] = field(default_factory=list)


class Recruiter:
    def __init__(self, xmlfile):
        self.filename = xmlfile                       

    def candidate_from_entry(self, title, text):
        if scraper.BLOCKED_LOCK.locked():
            sys.exit()

        print_logger.info(f"Processing [[{title}]].")

        cand = Candidate(title, text)

        # Get allowed refnames. Dictionary maps refname to match object of the citation definition
        refnames = dict()
        for m in re.finditer(fr'(?P<citation><ref +name *= *"?(?P<refname>[^>]+?)"? *>((?!<ref).)*{t_alternates}((?!<ref).)*</ref *>)', text, re.DOTALL):
            refnames[m.group('refname')] = m

        # pattern for allowed refnames
        allowed_refname = alternates(map(re.escape, refnames))

        ldref_re = fr'(?P<ldref><ref +name *= *"?(?P<ldrefname>{allowed_refname})"? */>)'
        rtref_re = alternates([citation_re,ldref_re]) if refnames else citation_re

        # (?!((?!<!--).)*-->) is for not inside comment
        # ((?!</?ref|\n\n).)*? is filler without ref tags or line breaks
        # (?!((?!<ref).)*</ref) is for not inside reference
        cand_re1 = fr'{rt_re}(?!((?!<ref).)*</ref)(?!((?!<!--).)*-->)((?!</?ref|\n\n).)*?{score_re}((?!\n\n).)*?(?P<refs>{anyrefs_re}{rtref_re}{anyrefs_re})[.]?'
        cand_re2 = fr'{score_re}(?!((?!<ref).)*</ref)(?!((?!<!--).)*-->)((?!</?ref|\n\n).)*?{rt_re}((?!\n\n).)*?(?P<refs>{anyrefs_re}{rtref_re}{anyrefs_re})[.]?'
        cand_re3 = fr'{t_rtprose}(?!((?!<!--).)*-->)((?!</?ref|\n\n).)*?(?P<refs>{rtref_re})'
        pats = map(re.compile, [cand_re1, cand_re2, cand_re3], [re.DOTALL]*3)

        all_matches = list(chain(*(p.finditer(text) for p in pats)))
        # if all_matches:
        #     return Entry(title)
        
        rtmatch_list = []
        span_set = set()      # different matches may be for the same prose
        id_set = set()
        def is_subspan(x, y):
            return y[0]<=x[0] and x[2]<=y[2]
        for m in all_matches:
            span = _find_span(m, title)

            # naively check if match is inside a template or table
            x1, x2 = span[0], text.find('\n\n', span[0])
            y = text[x1:x2]
            if y.count('{{') != y.count('}}'):
                continue
            if y.count('{|') != pattern_count(r'\|}(?!})', y):
                continue

            # check if is subspan of something already, or is strict superspan or something already
            skip_match = False
            for x in frozenset(span_set):
                if is_subspan(span, x):
                    skip_match = True
                    break
                elif is_subspan(x, span): 
                    span_set.remove(x)
                    rtmatch_list = [z for z in rtmatch_list if z[0].span != x]
                    break
                elif (x[0]<=span[0]<x[2]) or (span[0]<=x[0]<span[2]): # otherwise overlapping
                    scraper.BLOCKED_LOCK.acquire()
                    raise OverlappingMatchError(f"Overlapping matches found in {title}:\n{text[x[0]:x[2]]}\n\n{text[span[0]:span[2]]}")
            if skip_match:
                continue
            span_set.add(span)

            ref, initial_rt_id = _find_citation_and_id(title, m, refnames)
            id_set.add(initial_rt_id)
            rtmatch_list.append((RTMatch(span, ref), initial_rt_id))

        # if rtmatch_list:
        #     return Entry(title)

        cand.multiple_movies = len(id_set) > 1

        for rtmatch, initial_rt_id in rtmatch_list:
            cand.matches.append(rtmatch)
            if not rtmatch._load_rt_data(initial_rt_id, cand,
                make_guess=not cand.multiple_movies):
                self._needs_input_list.append( (cand, rtmatch, suggested_id(title)) )

        return cand if cand.matches else None



    def find_candidates(self, get_user_input = False):
        """
        Given an XmlDump, yields all pages (as a Candidate) in the dump
        which match at least one pattern in patterns.
        """
        # if we get blocked (status code 403), acquire the lock
        # to let other threads know
        total, count = 0, 0
        xml_entries = XmlDump(self.filename).parse()

        # Save pages which need user input for the end
        self._needs_input_list = []

        return_list = list()
        # 15 threads is fine, but don't rerun on the same pages immediately
        # after a run, or the caching may result in sending too many
        # requests too fast, and we'll get blocked.
        with ThreadPoolExecutor(max_workers = 15) as x:
            futures = (x.submit(self.candidate_from_entry, entry.title, entry.text)
                for entry in xml_entries)
            for future in as_completed(futures, timeout=None):
                total += 1
                try:
                    cand = future.result()
                except SystemExit:
                    x.shutdown(wait=True, cancel_futures=True)
                    logger.error("Exiting program.")
                    sys.exit()
                if cand:
                    return_list.append(cand)

        if get_user_input:
            self._process_needs_input_list()

        logger.info(f"Found {len(return_list)} candidates out of {total} pages")
        print_logger.info(f"Found {len(return_list)} candidates out of {total} pages")
        return return_list

    def _process_needs_input_list(self):
        to_return = []
        for cand, rtmatch, suggest_id in self._needs_input_list:
            while True:
                newid = self._ask_for_id(cand, rtmatch, suggest_id)
                if not newid or rtmatch._load_rt_data(newid, cand):
                    break
                else:
                    print(f"Problem getting Rotten Tomatoes data with id {newid}\n")
                    continue

    def _ask_for_id(self, cand, rtmatch, suggested_id):
        """
        Asks for a user decision regarding the Rotten Tomatoes id for a film.
        """
        logger.debug(f"Asking for id for [[{cand.title}]]")
        title, text = cand.title, cand.text
        i, j = rtmatch.span[0], rtmatch.span[2]
        warning = ''
        if cand.multiple_movies:
            warning = 'WARNING: More than one movie url detected in this article.\n'
        prompt = f"""\033[96mNo working id found for a match in [[{title}]].\033[0m
\033[93m{warning}Context------------------------------------------------------------------------\033[0m
{text[i-60: i]}\033[1m{text[i: j]}\033[0m{text[j: j+50]}
\033[93m-------------------------------------------------------------------------------\033[0m
Please select an option:
    1) enter id manually (suggested: {suggested_id})
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
def _find_span(match, title):
    """
    This function tries find the beginning of
    the sentence containing the Rotten Tomatoes rating info.

    NOTE: There are edge cases where the start position found
    by this function
    is in fact NOT the start of the desired sentence.
    For example, if the movie title is 'Mr. Bobby' and it isn't italicized
    in the Wikitext, then this function might identify the start at 'B'.
    
    Args:
        match: match object which identified this potential candidate
    """
    text, matchstart = match.string, match.start()
    text = text.replace('“', '"').replace('”', '"')
    i, last = matchstart - 1, matchstart

    brackets_re = r'\s+\([^()]+?\)$'
    title = re.sub(brackets_re, '', title)

    while i >= text.rfind('\n', 0, matchstart):
        #print(text[i:i+7])
        truncated = text[:i+1]
        if truncated.endswith(title):
            i -= len(title) - 1
            continue

        # jump over links
        if truncated.endswith(']]'):
            i = text.rfind('[[', 0, i-1)
            continue

        # skip comments
        if truncated.endswith('-->'):
            i = text.rfind('<!--', 0, i-2) - 1
            continue

        # skip references
        if truncated.endswith("</ref>") or truncated.endswith("/>"):
            i = text.rfind("<ref", 0, i) - 1
            continue

        if text[i] == '\n':
            break
        if text[i:i+2] in ('. ', '.<', '."', '".') and text[i-1] not in string.ascii_uppercase:
            break
        if text[i:i+3] == '."<':
            break

        if text[i] in string.ascii_letters + string.digits + "'{[":
            last = i
        i -= 1

    i = last
    while text[i] in ' "':
        i += 1
    return (i, match.start('refs'), match.end())


def _find_citation_and_id(title, m, refnames):
    groupdict = m.groupdict()
    if ldrefname := groupdict.get('ldrefname'):
        ref = Reference(text=refnames[ldrefname].group(),
            name=ldrefname, list_defined=True)
        groupdict = refnames[ldrefname].groupdict()
    else:
        ref = Reference(groupdict['citation'], groupdict.get('refname'))

    if rt_id := groupdict.get('rt_id'):
        return ref, rt_id
    elif citert := groupdict.get('citert'):
        d = parse_template(citert)[1]
        return ref, "m/" + d['id']
    elif rt := groupdict.get('rt'):
        d = parse_template(rt)[1]
        if '1' in d:
            return ref, ["m/",""][d['1'].startswith("m/")] + d['1']
        elif 'id' in d:
            return ref, ["m/",""][d['id'].startswith("m/")] + d['id']
        elif p := _p1258(title):
            return ref, p
    raise ValueError(f'Problem getting citation and id for a match in [[{title}]]')

def _p1258(title):
    WIKIDATA_LOCK.acquire()
    page = pwb.Page(pwb.Site('en','wikipedia'), title)
    item = pwb.ItemPage.fromPage(page)
    item.get()
    WIKIDATA_LOCK.release()
    if 'P1258' in item.claims:
        return item.claims['P1258'][0].getTarget()
    return None

def suggested_id(title):
    GOOGLESEARCH_LOCK.acquire()
    #time.sleep(1)       # help avoid getting blocked, better safe than sorry
    print_logger.info(f"GETTING SUGGESTED ID for {title}.")
    url = lucky(title + ' movie site:rottentomatoes.com/m/',
        user_agent=scraper.USER_AGENT)
    GOOGLESEARCH_LOCK.release()
    suggested_id = url.split('rottentomatoes.com/m/')[1]
    return 'm/' + suggested_id.split('/')[0]


if __name__ == "__main__":
    pass





