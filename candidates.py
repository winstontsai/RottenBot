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
import urllib.error # for googlesearch maybe
import logging
logger = logging.getLogger(__name__)

print_logger = logging.getLogger('print_logger')

from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
from threading import Lock
from dataclasses import dataclass, field
from itertools import chain
from collections import defaultdict, namedtuple

import requests
import pywikibot as pwb
import wikitextparser as wtp

from pywikibot.xmlreader import XmlDump
from googlesearch import lucky

import scraper
from scraper import RTMovie
from patterns import *
from findspan import _find_span333,_find_span222,_find_span
################################################################################
WIKIDATA_LOCK = Lock()
GOOGLESEARCH_LOCK = Lock()
WTP_LOCK = Lock()

class OverlappingMatchError(Exception):
    pass

Entry = namedtuple('Entry',['title'])

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
        guessid = googled_id(title)

        try:
            movie = RTMovie(guessid)
        except Exception:
            pass
        else:
            def probably_correct():
                text = cand.text
                lead = text[:text.find('==')]
                words_to_check_for = set([' ' + movie.year])
                names = chain.from_iterable(name.split() for name in movie.director+movie.writer)
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
    matches: list[RTMatch] = field(default_factory=list)
    multiple_movies: bool = False # some articles have RT stuff for more than one movie, e.g. sequels


class Recruiter:
    def __init__(self, xmlfile):
        self.filename = xmlfile                       

    def candidate_from_entry(self, title, text):
        if scraper.BLOCKED_LOCK.locked():
            sys.exit()

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

        # (?!((?!<!--).)*-->) is for not inside comment
        # ((?!</?ref|\n\n).)*? is filler without ref tags or line breaks
        # (?!((?!<ref).)*</ref) is for not inside reference
        notinref = r'(?!((?!<ref).)*</ref)'
        notincom = r'(?!((?!<!--).)*-->)'
        #cand_re1 = fr'{rt_re}{notinref}{notincom}((?!</?ref|\n[\n*]|==).)*?{score_re}((?!\n\n|==).)*?(?P<refs>{anyrefs_re}{rtref_re}{anyrefs_re})'
        #cand_re2 = fr'{score_re}{notinref}{notincom}((?!</?ref|\n[\n*]|==).)*?{rt_re}((?!\n\n|==).)*?(?P<refs>{anyrefs_re}{rtref_re}{anyrefs_re})'
        cand_re3 = fr'{t_rtprose}{notincom}((?!</?ref|\n\n|==).)*?(?P<refs> ?{rtref_re})'
        #pats = map(re.compile, [cand_re1, cand_re2, cand_re3], [re.DOTALL]*3)

        cand_re4 = fr'(?:({rt_re})|{score_re}){notinref}{notincom}((?!</?ref|\n[\n*]|==).)*?(?(1){score_re}|{rt_re})((?!\n\n|==).)*?(?P<refs>{anyrefs_re}{rtref_re}{anyrefs_re})|{cand_re3}'
        #pats = [re.compile(cand_re4, flags=re.DOTALL)]

        #all_matches = list(chain(*(p.finditer(text) for p in pats)))
        #print(all_matches)

        rtmatch_list = []
        span_set = set()      # different matches may be for the same prose
        id_set = set()

        previous_end = -666
        for m in re.finditer(cand_re4, text, flags=re.DOTALL):
            if _inside_table_or_template( m):
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
            rtmatch_list.append((RTMatch(span, ref), initial_rt_id))

        # for m in all_matches:
        #     if _inside_table_or_template( m.span() , text):
        #         continue

        #     if m['rtprose']:
        #         span = m.span()
        #     else:
        #         span = _find_span333(m, title)

        #     # check if is subspan of something already, or is strict superspan or something already
        #     # skip_match = False
        #     # for x in frozenset(span_set):
        #     #     if is_subspan(span, x):
        #     #         skip_match = True
        #     #         #print_logger.info('SUBSPAN FOUND\n' +text[span[0]:span[1]] + '\n\nis a subspan of\n\n' + text[x[0]:x[1]])
        #     #         break
        #     #     elif is_subspan(x, span):
        #     #         span_set.remove(x)
        #     #         rtmatch_list = [z for z in rtmatch_list if z[0].span != x]
        #     #         #print_logger.info('STRICT SUBSPAN FOUND\n' +text[x[0]:x[1]] + '\n\nis a subspan of\n\n' + text[span[0]:span[1]])
        #     #         break
        #     #     elif (x[0]<=span[0]<x[1]) or (span[0]<=x[0]<span[1]): # otherwise overlapping
        #     #         scraper.BLOCKED_LOCK.acquire()
        #     #         raise OverlappingMatchError(f"Overlapping matches found in {title}:\n{text[x[0]:x[1]]}\n\n{text[span[0]:span[1]]}")
        #     # if skip_match:
        #     #     continue
        #     # span_set.add(span)

        #     ref, initial_rt_id = _find_citation_and_id(title, m, refnames)
        #     id_set.add(initial_rt_id)
        #     rtmatch_list.append((RTMatch(span, ref), initial_rt_id))

        if rtmatch_list:
            return Candidate(title, text, matches=[x[0] for x in rtmatch_list],
                multiple_movies=len(id_set) > 1)

        cand = Candidate(title, text, multiple_movies=len(id_set) > 1)
        for rtmatch, initial_rt_id in rtmatch_list:
            cand.matches.append(rtmatch)
            if not rtmatch._load_rt_data(initial_rt_id, cand,
                make_guess=not cand.multiple_movies):
                self._needs_input_list.append( (cand, rtmatch, googled_id(title)) )

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
        with ProcessPoolExecutor(max_workers = 8) as x:
            futures = (x.submit(self.candidate_from_entry, entry.title, entry.text)
                for entry in xml_entries)
            for future in as_completed(futures, timeout=None):
                total += 1
                try:
                    cand = future.result()
                except Exception as e:
                    x.shutdown(wait=True, cancel_futures=True)
                    logger.exception("Exiting program.")
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
        i, j = rtmatch.span[0], rtmatch.span[1]
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
def _find_citation_and_id(title, m, refnames):
    groupdict = m.groupdict()
    if ldrefname := groupdict.get('ldrefname'):
        ref = Reference(text=refnames[ldrefname][0], name=ldrefname, list_defined=True)
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

def googled_id(title):
    GOOGLESEARCH_LOCK.acquire()
    #time.sleep(1)       # help avoid getting blocked, better safe than sorry
    print_logger.info(f"GETTING SUGGESTED ID for {title}.")
    url = lucky(title + ' movie site:rottentomatoes.com/m/',
        user_agent=scraper.USER_AGENT)
    GOOGLESEARCH_LOCK.release()
    suggested_id = url.split('rottentomatoes.com/m/')[1]
    return 'm/' + suggested_id.split('/')[0]



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


if __name__ == "__main__":
    pass





