# This module does some preprocessing.
# It identifies "candidate" pages that contain Rotten Tomatoes rating info,
# finds the corresponding Rotten Tomatoes data if possible,
# and also finds (or at least tries to) the start of the sentence in which
# the rating info is contained.
# In particular, a candidate should always have a Tomatometer score available.
#
# Multiple matches IF more than one match with distinct initial rt_ids
################################################################################
import re
import sys
import webbrowser
import time
import logging
logger = logging.getLogger(__name__)
print_logger = logging.getLogger('print_logger')

from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from dataclasses import dataclass
from itertools import chain
from collections import defaultdict

import requests
import urllib.error # for google search maybe
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

@dataclass
class Reference:
    refname: str = None
    reftext: str = None
    ld: bool = False

@dataclass
class Candidate:
    title: str                   # article title
    pagetext: str                # wikitext
    span: tuple[int, int, int] 
    prose: str
    ref: Reference
    rt_data: RTMovie = None
    multiple_matches: bool = False
    multiple_movies: bool = False

    def _load_rt_data(self, movieid, make_guess = False):
        if scraper.BLOCKED_LOCK.locked():
            sys.exit()

        title = self.title

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
            text = self.pagetext
            lead = text[:text.find('==')]
            words_to_check_for = set([f"'''''{movie.title}'''''", ' '+movie.year])
            names = chain(*(name.split() for name in movie.director+movie.writer))
            words_to_check_for.update(x for x in names if x[-1] != '.')
            if all(x in lead for x in words_to_check_for):
                self.rt_data = movie
                return True

        logger.info(f"Google search for [[{title}]] failed.")
        return False


class Recruiter:
    def __init__(self, xmlfile):
        self.filename = xmlfile                       

    # entry just needs .title and .text attributes for the page we are interested in
    def candidate_from_entry(self, title, text):
        if scraper.BLOCKED_LOCK.locked():
            sys.exit()

        print_logger.info(f"Processing [[{title}]].")

        # Get allowed refnames. Dictionary maps refname to match object of the citation definition
        refnames = dict()
        for m in re.finditer(fr'(?P<citation><ref +name *= *"?(?P<refname>[^>]+?)"? *>((?!<ref).)*{t_alternates}((?!<ref).)*</ref *>)', text, re.DOTALL):
            refnames[m.group('refname')] = m

        # pattern for allowed refnames
        allowed_refname = alternates(map(re.escape, refnames))

        ldref_re = fr'(?P<ldref><ref +name *= *"?(?P<ldrefname>{allowed_refname})"? */>)'
        rtref_re = alternates([citation_re,ldref_re]) if refnames else citation_re

        cand_re1 = fr'{rt_re}(?!((?!<!--)[^\n])*-->)((?!</?ref)[^\n])*?{score_re}((?!</?ref)[^\n])*?{anyrefs_re}{rtref_re}{anyrefs_re}[.]?'
        cand_re2 = fr'{score_re}(?!((?!<!--)[^\n])*-->)((?!</?ref)[^\n])*?{rt_re}((?!</?ref)[^\n])*?{anyrefs_re}{rtref_re}{anyrefs_re}[.]?'
        cand_re3 = fr'{t_rtprose}((?!</?ref).)*?{rtref_re}'
        pats = list(map(re.compile, [cand_re1, cand_re1, cand_re3], [re.DOTALL]*3))

        all_matches = chain(*(p.finditer(text) for p in pats))
        
        cand_list = []
        span_set = set()      # different matches may be for the same prose
        id_set = set()
        for m in all_matches:
            span, prose = _find_span_and_prose(m)
            if span in span_set:
                continue
            else:
                for x in span_set: # not seen before, but could happen
                    if (x[0]<=span[0] and x[2]>span[0]) or (span[0]<=x[0] and span[2]>x[0]):
                        logger.error(f"Overlapping matches found in {title}",exc_info=True)
                        raise OverlappingMatchError
            span_set.add(span)

            ref, initial_rt_id = _find_citation_and_id(title, m, refnames)
            id_set.add(initial_rt_id)

            cand = Candidate(
                    title = title,
                    pagetext = text,
                    span = span,
                    prose = prose,
                    ref = ref,)
            cand_list.append((cand, initial_rt_id))

        if len(span_set)>1:
            for cand, rtid in cand_list:
                cand.multiple_matches = True
        if len(id_set)>1:
            for cand, rtid in cand_list:
                cand.multiple_movies = True

        to_return = []
        for cand, initial_rt_id in cand_list:
            if cand._load_rt_data(initial_rt_id, make_guess=not cand.multiple_movies):
                if cand.rt_data.tomatometer_score:
                    to_return.append(cand)
            else:
                self.needs_input_list.append(cand)
        return to_return



    def find_candidates(self, get_user_input = True):
        """
        Given an XmlDump, yields all pages (as a Candidate) in the dump
        which match at least one pattern in patterns.
        """
        # if we get blocked (status code 403), acquire the lock
        # to let other threads know
        total, count = 0, 0
        xml_entries = XmlDump(self.filename).parse()

        # Save pages which need user input for the end
        self.needs_input_list = []

        return_dict = defaultdict(list)
        # 15 threads is fine, but don't rerun on the same pages immediately
        # after a run, or the caching may result in sending too many
        # requests too fast, and we'll get blocked.
        with ThreadPoolExecutor(max_workers=15) as x:
            futures = (x.submit(self.candidate_from_entry, entry.title, entry.text)
                for entry in xml_entries)
            for future in as_completed(futures, timeout=None):
                total += 1
                try:
                    cands = future.result()
                except SystemExit:
                    x.shutdown(wait=True, cancel_futures=True)
                    logger.error("Exiting program.")
                    sys.exit()
                if cands:
                    count += len(cands)
                    return_dict[cands[0].title] = cands
                # for x in cands:
                #     count += 1
                #     yield x

        if get_user_input:
            for cand in self._process_needs_input_list():
                count += 1
                return_dict[cands.title].append(cand)


        logger.info(f"Found {count} candidates out of {total} pages")
        print_logger.info(f"Found {count} candidates out of {total} pages")
        return return_dict

    def _process_needs_input_list(self):
        for cand in self.needs_input_list:
            logger.info(f"Processing [[{cand.title}]] in needs_input_list")
            while True:
                movieid = self._ask_for_id(cand)
                if movieid is None:
                    break
                if cand._load_rt_data(movieid):
                    if cand.rt_data.tomatometer_score:
                        yield cand
                        break
                else:
                    print(f"Problem getting Rotten Tomatoes data with id {newid}\n")
                    continue

    def _ask_for_id(self, cand):
        """
        Asks for a user decision regarding the Rotten Tomatoes id for a film.
        """
        logger.debug(f"Asking for id for [[{cand.title}]]")
        title, pagetext = cand.title, cand.pagetext
        i, j = cand.span[0], cand.span[2]
        warning = ''
        if cand.multiple_movies:
            warning = 'WARNING: More than one movie url detected in this article.\n'
        prompt = f"""\033[96mNo working id found for a match in [[{cand.title}]].\033[0m
\033[93m{warning}Context------------------------------------------------------------------------\033[0m
{cand.pagetext[i-60: i]}\033[1m{cand.pagetext[i: j]}\033[0m{cand.pagetext[j: j+50]}
\033[93m-------------------------------------------------------------------------------\033[0m
Please select an option:
    1) enter id manually
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
            logger.info(f"Entered id '{newid}' for [[{cand.title}]]")
            return newid
        elif user_input == '3':
            logger.info(f"Skipping article [[{title}]]")
            return None
        elif user_input == '4':
            print_logger.info("Quitting program.")
            sys.exit()                

# ===========================================================================================
def _find_span_and_prose(match):
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
    text = match.string
    text = text.replace('“', '"').replace('”', '"')
    italics = False
    i = match.start() - 1
    while i >= 0:
        c = text[i]
        # skip over comments. As a result, comments may be removed
        if text[i-2: i+1] == '-->':
            i = text.rfind('<!--', 0, i) - 1
            continue
        if c in '\n>' or (c == '.' and not italics and text[i+1] in ' "'):
            i += 1
            if text[i] == '"':
                i += 1
            break
        elif c == "'" == text[i + 1]:
            italics = not italics
        i -= 1

    while text[i] == ' ':
        i += 1

    mid = text.find('<ref', i)
    end = match.end()
    return (i, mid, end), text[i : end]


def _find_citation_and_id(title, m, refnames):
    groupdict = m.groupdict()
    ref = Reference()
    if ldrefname := groupdict.get('ldrefname'):
        ref.reftext = refnames[ldrefname].group()
        ref.refname = ldrefname
        ref.ld = True
        groupdict = refnames[ldrefname].groupdict()
    else:
        ref.reftext = groupdict['citation']
        ref.refname = groupdict.get('refname')

    if rt_id := groupdict.get('rt_id'):
        return ref, rt_id
    elif citert := groupdict.get('citert'):
        d = parse_template(citert)[1]
        return ref, "m/" + d['id']
    elif rt := groupdict.get('rt'):
        d = parse_template(rt)[1]
        if '1' in d.keys() or 'id' in d.keys():
            key = '1' if '1' in d.keys() else 'id'
            return ref, ["m/",""][d[key].startswith("m/")] + d[key]
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
    print_logger.info(f"GETTING SUGGESTED ID for {title}.")
    time.sleep(1)       # help avoid getting blocked, better safe than sorry
    url = lucky(title + ' movie site:rottentomatoes.com/m/',
        user_agent=scraper.USER_AGENT)
    GOOGLESEARCH_LOCK.release()
    # except StopIteration:
    #     GOOGLESEARCH_LOCK.release()
    #     print_logger.exception(f"Error while getting suggested id for {title}")
    #     raise
    suggested_id = url.split('rottentomatoes.com/m/', maxsplit=1)[1]
    return 'm/' + suggested_id.split('/', maxsplit=1)[0]


if __name__ == "__main__":
    print(suggested_id('endgame avengers'))



