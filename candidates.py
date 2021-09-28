# This module does some preprocessing.
# It identifies "candidate" pages that contain Rotten Tomatoes rating info
# and finds the corresponding Rotten Tomatoes data if possible.
################################################################################
import logging
import multiprocessing
import sys
import time
import webbrowser

from concurrent.futures import as_completed, ProcessPoolExecutor
from dataclasses import dataclass, field
from itertools import chain

import pywikibot as pwb
import regex as re
import wikitextparser as wtp

from colorama import Fore, Style
from googlesearch import lucky
from pywikibot import Page, Site, ItemPage
from pywikibot.xmlreader import XmlDump

import scraper

from patterns import *
from wdeditor import *

logger = logging.getLogger(__name__)
################################################################################

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
    movie: scraper.RTMovie = None
    qid: str = None   # special value 'connected' means use connected Wikidata item
    initial_rtid: str = None
    safe_to_guess: bool = False

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

def _init(lock1, lock2, lock3):
    """
    To be used with Executor in find_candidates.
    """
    global WIKIDATA_LOCK
    global GOOGLESEARCH_LOCK
    global WQS_LOCK
    WIKIDATA_LOCK, GOOGLESEARCH_LOCK, WQS_LOCK = lock1, lock2, lock3

def find_candidates(xmlfile, get_user_input = False):
    """
    Given an XmlDump, yields all pages (as a Candidate) in the dump
    which match at least one pattern in patterns.
    """
    total, count = 0, 0
    xml_entries = XmlDump(xmlfile).parse()

    WIKIDATA_LOCK = multiprocessing.Lock()
    GOOGLESEARCH_LOCK = multiprocessing.Lock()
    WQS_LOCK = multiprocessing.Lock()   # Wikidata Query Service
    with ProcessPoolExecutor(max_workers=14,
            initializer=_init, initargs=(WIKIDATA_LOCK,GOOGLESEARCH_LOCK, WQS_LOCK)) as executor:
        futures = {executor.submit(candidate_from_entry, e) : e.title for e in xml_entries}

        rtid_to_qid = RTID_to_QID()

        for future in as_completed(futures):
            total += 1
            try:
                cand = future.result()
                # Now some extra processing, which means finding missing movies
                # and finding the corresponding QID.
                # Return only those matches with a Tomatometer score and QID
                if get_user_input:
                    _ask_for_movies(cand)
                cand.matches = [x for x in cand.matches if x.movie and x.movie.tomatometer_score]

                # find qid, without user input
                for rtm in cand.matches:
                    rtm.qid = _find_qid(cand, rtm, rtid_to_qid)
                    # for the future, just in case
                    rtid_to_qid[rtm.movie.short_url] = rtm.qid
                    rtid_to_qid[rtm.initial_rtid]    = rtm.qid

                # find missing qids
                if get_user_input:
                    _ask_for_qids(cand, rtid_to_qid)
                cand.matches = [x for x in cand.matches if x.qid]
            except (SystemExit, KeyboardInterrupt):
                executor.shutdown(wait=True, cancel_futures=True)
                logger.exception("SHUTTING DOWN.")
                print('SHUTTING DOWN due to SystemExit or KeyboardInterrupt.')
                raise
            except Exception:
                executor.shutdown(wait=True, cancel_futures=True)
                logger.exception("SHUTTING DOWN.")
                print('SHUTTING DOWN due to an exception.')
                raise
            if cand.matches:
                print(f"Found candidate [[{futures[future]}]].")
                count += 1
                yield cand
    logger.info(f"Found {count} candidates out of {total} pages")
    print(f"Found {count} candidates out of {total} pages")

def candidate_from_entry(entry):
    title, text = entry.title, entry.text
    # Get allowed refnames.
    # Dictionary maps refname to match object of the citation definition.
    refnames = dict()
    for m in re.finditer(fr'<ref +name\s*=\s*"?(?P<refname>[^>]+?)"?\s*>((?!<ref).)*{t_alternates}((?!<ref).)*</ref\s*>', text, flags=re.S|re.I):
        refnames[m['refname']] = m

    rtref_re = citation_re
    if refnames:
        allowed_refname = alternates(map(re.escape, refnames))
        ldref_re = fr'<ref +name\s*=\s*"?(?P<ldrefname>{allowed_refname})"?\s*/>|{{{{\s*[rR]\s*\|\s*(?P<ldrefname>{allowed_refname})\s*}}}}'
        rtref_re = alternates([citation_re,ldref_re])
    rtref_re = fr'\s*{rtref_re}'
    
    final_re = fr'{template_re}(?:{t_rtprose}|(?:{rt_re+notincurly}|{score_re}){notinref+notincom}((?!</?ref|\n\n|==).)*?(?(rot){score_re}|{rt_re+notincurly})){notincom+notinbadsection}(?:((?!\n\n|==).)*?(?P<refs>{anyrefs_re}{rtref_re}{anyrefs_re2}))?'
    # print(final_re)

    cand = Candidate(title, text)
    previous_end = -9999
    id_set = set()
    for m in re.finditer(final_re, text, flags=re.S|re.I):
        #print(m)
        span = _find_span(m, title)
        if span[0] < previous_end:
            continue
        previous_end = span[1]

        ref, initial_rtid = _find_citation_and_id(title, m, refnames)
        id_set.add(initial_rtid)

        rtm = RTMatch(span, ref)
        rtm.initial_rtid = initial_rtid
        cand.matches.append(rtm)

    if not cand.matches:
        return cand

    j = text.index('\n==')


    # If it is the only match in the lead section, we assume the article
    # is about the movie whose RT data is being displayed. Hence the connected
    # Wikidata item is also for that same movie.
    # Similarly, if it is the only match after the lead section, we assume the same.
    # Otherwise we do not assume anything.
    if len(cand.matches) == 1:
        cand.matches[0].safe_to_guess = True
    else:
        if cand.matches[0].span[0] < j < cand.matches[1].span[0]:
            cand.matches[0].safe_to_guess = True
        if cand.matches[-2].span[0] < j < cand.matches[-1].span[0]:
            cand.matches[-1].safe_to_guess = True

    for rtm in cand.matches:
        rtm.movie = _find_RTMovie(cand, rtm, make_guess=rtm.safe_to_guess)
        # If there is an initial RTID, wait a bit and try again
        if not rtm.movie and rtm.initial_rtid:
            time.sleep(60)
            rtm.movie = _find_RTMovie(cand, rtm, make_guess=rtm.safe_to_guess)
    return cand

def _ask_for_movies(cand):
    for rtm in cand.matches:
        if not rtm.movie:
            rtm.movie = _ask_for_movie(cand, rtm)

def _ask_for_movie(cand, rtmatch):
    """
    Returns None if the user decides to skip.
    Otherwise returns the Rotten Tomatoes movie chosen by the user.
    """
    title, text = cand.title, cand.text
    i, j = rtmatch.span[0], rtmatch.span[1]
    pspan = paragraph_span((i,j), text)
    if 'tomatoes.com/tv/' in text[pspan[0]:pspan[1]]:
        return None
    print(f"""{Fore.CYAN+Style.BRIGHT}Need Rotten Tomatoes ID for a match in [[{title}]].{Style.RESET_ALL}
{Fore.GREEN+Style.BRIGHT}Context------------------------------------------{Style.RESET_ALL}
{text[pspan[0]: i] + Style.BRIGHT + text[i: j] + Style.RESET_ALL + text[j: pspan[1]]}
{Fore.GREEN+Style.BRIGHT}-------------------------------------------------{Style.RESET_ALL}""")

    while True:
        prompt = 'Enter Rotten Tomatoes ID (or open in [b]rowser, [s]kip, or [q]uit): '
        while not re.fullmatch(r'm/[-a-z0-9_]+', (user_input:=input(prompt)) ):
            if user_input == 'b':
                webbrowser.open(Page(Site('en','wikipedia'), title).full_url())
            elif user_input == 's':
                print(f"Skipping match.")
                return None
            elif user_input == 'q':
                print("Quitting program.")
                sys.exit()
            else:
                print("ID must match the regex 'm/[-a-z0-9_]+'.")
        rtmatch.initial_rtid = user_input
        if movie := _find_RTMovie(cand, rtmatch):
            return movie
        print(f"Problem getting Rotten Tomatoes data with id {user_input}.\n")


def _ask_for_qids(cand, rtid_to_qid):
    for rtid in set(rtm.movie.short_url for rtm in cand.matches if not rtm.qid):
        newqid = _ask_for_qid(cand, rtid)
        for rtm in cand.matches:
            if rtm.movie.short_url == rtid:
                rtm.qid = newqid

def _ask_for_qid(cand, rtid):
    """
    Returns None if the user decides to skip.
    Otherwise returns the QID provided by the user.
    """
    print(f"""{Fore.MAGENTA+Style.BRIGHT}Need QID for Rotten Tomatoes ID {rtid}.{Style.RESET_ALL}""")

    prompt = 'Enter QID (or open in [b]rowser, [s]kip, or [q]uit): '
    while not re.fullmatch(r'Q[0-9]+', (user_input:=input(prompt)) ):
        if user_input == 'b':
            webbrowser.open(Page(Site('en','wikipedia'), cand.title).full_url())
            webbrowser.open(scraper.rt_url(rtid))
        elif user_input == 's':
            print(f"Skipping match."); return None
        elif user_input == 'q':
            print("Quitting program."); sys.exit()
        else:
            print("QID must match the regex 'Q[0-9]+'.")
    return user_input

# ===========================================================================================
def _find_span(match, title):
    if match['rtprose'] and match['refs']:
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

    p4 = re.compile(r'(?:([.!?][ \']?"|[!?]|(?<![A-Z])\.' + no_bad_abbr_re + r')(({{a+}})+|(\s*[@`]+)+|(?=\s+[^a-z]))|}}\s*@+|\n)\s*', flags=re.REVERSE)
    m = p4.search(text, 0, matchstart+1)
    i = m.end()

    p5 = re.compile(r'([.!?][ \']?"|[!?]|(?<![A-Z])\.' + no_bad_abbr_re + r')(({{a+}})+|(\s*[@`]+)+|(?=\s+[^a-z]))|}}\s*@+|(?=\n\n|\n==)')
    m = p5.search(text, pos=rindex_pattern(r'\w', text, 0, match.end()))
    j = m.end()

    return i, j

def P1258(title):
    with WIKIDATA_LOCK:
        try:
            item = ItemPage.fromPage(Page(Site('en','wikipedia'), title))
        except pwb.exceptions.NoPageError:
            return None
        item.get()
    if rtid_claims := item.claims.get(P_ROTTEN_TOMATOES_ID):
        if rtid_claims[0].target.startswith('m/'):
            return max(rtid_claims, key=lambda c: date_from_claim(c)).target
    return None

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
        d = parse_template(citert)[1]
        if not d['type'][0].lower() == 'm':
            return None, None
        movieid = "m/" + d['id']
    elif rt := m['rt']:
        d = parse_template(rt)[1]
        if 'id' in d:
            movieid = d['id']
        elif '1' in d:
            movieid = d['1']
        elif (movieid := P1258(title)) is None:
                return None, None
        if not movieid.startswith('m/'):
            movieid = 'm/' + movieid
    return ref, movieid.lower()

def googled_id(title):
    logger.info(f"GOOGLING ID for [[{title}]].")
    with GOOGLESEARCH_LOCK:
        time.sleep(5)      # avoid getting blocked, better safe than sorry
        try:
            url = lucky(title + ' movie site:rottentomatoes.com/m/', user_agent=scraper.USER_AGENT)
        except Exception:
            return None
    return re.search(url_re, url)['rt_id']

def _find_RTMovie(cand, rtm, make_guess = False):
    """
    Attempt to find correct Rotten Tomatoes movie for the RTMatch rtm.
    Uses rtm.initial_rtid for initial guess.
    """
    seen_ids = {rtm.initial_rtid, None}
    title, text = cand.title, cand.text
    try:
        if rtm.initial_rtid:
            return scraper.RTMovie(rtm.initial_rtid)
    except Exception:
        pass

    if not make_guess:
        return None

    # Check External links section
    id_from_external_links = None
    if m := re.search(section('External links'), text):
        if m := re.search( fr'(?:{t_rt}|{url_re})', text[m.end():]):
            if m['rt_id']:
                id_from_external_links = m['rt_id']
            else:
                d = parse_template(m[0])[1]
                id_from_external_links = d.get('id') or d.get('1')
                if id_from_external_links and not id_from_external_links[:2]=='m/':
                    id_from_external_links = 'm/'+id_from_external_links
    if id_from_external_links not in seen_ids:
        seen_ids.add(id_from_external_links)
        try:
            return scraper.RTMovie(id_from_external_links)
        except Exception:
            pass

    # Check connected Wikidata item
    if (p := P1258(title)) not in seen_ids:
        seen_ids.add(p)
        try:
            return scraper.RTMovie(p)
        except Exception:
            pass

    # Check Google
    def probably_correct():
        lead = text[:text.index('\n==')]
        if m := re.search(infobox_film_re, text, flags=re.S|re.I):
            infobox = m[0]
        else:
            infobox = lead
        dnames = chain.from_iterable(name.split() for name in movie.director)
        dnames = [x for x in dnames if x[-1] != '.']

        if any(x not in infobox for x in dnames+[movie.year]):
            return False
        if re.search(re.escape(movie.title), infobox, flags=re.S|re.I):
            return True
        if not re.search(f"''{re.escape(movie.title)}''", lead, flags=re.S|re.I):
            return False
        if not movie.runtime:
            return False
        z = re.findall(r'\d+', movie.runtime)
        if len(z) == 1:
            z = ['0'] + z
        try:
            hours, minutes = map(int, z)
        except ValueError:
            raise ValueError(f'Check runtime for {movie.title}.')

        return f'{60*hours+minutes} min' in infobox

    if (gid := googled_id(title)) not in seen_ids:
        try:
            movie = scraper.RTMovie(gid)
        except Exception:
            pass
        else:
            if probably_correct():
                return movie

def _find_qid(cand, rtm, rtid_to_qid):
    """
    Find qid for RTMatch object x.
    x should have movie.tomatometer_score
    """
    if b := rtid_to_qid[rtm.movie.short_url] or rtid_to_qid[rtm.initial_rtid]:
        return b

    try:
        item = ItemPage.fromPage(Page(Site('en','wikipedia'), cand.title))
    except pwb.exceptions.NoPageError:
        return None

    if rtm.safe_to_guess: # and FilmTypes.has_film_type(item):
        return item.getID()

    for claim in sorted(item.claims.get(P_ROTTEN_TOMATOES_ID, []),
            key=lambda c: date_from_claim(c), reverse=True):
        try:
            movie = RTMovie(claim.target)
        except Exception:
            continue
        if movie.short_url == rtm.movie.short_url:
            return item.getID()

if __name__ == "__main__":
    pass


