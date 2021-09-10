# This module does some preprocessing.
# It identifies "candidate" pages that contain Rotten Tomatoes rating info
# and finds the corresponding Rotten Tomatoes data if possible.
################################################################################
import sys
import webbrowser
import time
import multiprocessing
import urllib.error # for googlesearch maybe
import logging
logger = logging.getLogger(__name__)

print_logger = logging.getLogger('print_logger')

from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from itertools import chain

import regex as re
import wikitextparser as wtp

from pywikibot import Page, Site, ItemPage
from pywikibot.xmlreader import XmlDump
from googlesearch import lucky
from colorama import Fore, Style

import scraper
import wdeditor
from patterns import *
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
    qid: str = None

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
            initializer=_init, initargs=(WIKIDATA_LOCK,GOOGLESEARCH_LOCK, WQS_LOCK)) as x:
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
        if rtmatch.movie:
            with WQS_LOCK:
                rtmatch.qid = wdeditor.qid_from_movieid(rtmatch.movie.short_url)
            # if not rtmatch.qid and safe_to_guess:
            #     with WIKIDATA_LOCK:
            #         item = ItemPage.fromPage(Page(Site('en','wikipedia'), title))
            #         qid = item.getID()
            #     query = "SELECT WHERE {?item wdt:P31 ?filmclass. ?filmclass wdt:P279* wd:Q11424.}"
            #     query = query.replace('?item', 'wd:' + qid)
            #     with WQS_LOCK:
            #         if wdeditor.get_results(query):
            #             rtmatch.qid = qid

        cand.matches.append(rtmatch)

    if cand.matches:
        return cand

def _process_needs_input_movies(cand):
    for rtm in cand.matches:
        if not rtm.movie:
            while True:
                newid = _ask_for_rtid(cand, rtm)
                if newid is None:
                    break
                if z := _find_RTMovie(cand, newid):
                    rtm.movie = z
                    with WQS_LOCK:
                        rtm.qid = wdeditor.qid_from_movieid(rtm.movie.short_url)
                    break
                print(f"Problem getting Rotten Tomatoes data with id {newid}.\n")
        if rtm.movie and not rtm.qid:
            rtm.qid = _ask_for_qid(cand, rtm)

def _ask_for_rtid(cand, rtmatch):
    title, text = cand.title, cand.text
    i, j = rtmatch.span[0], rtmatch.span[1]
    pspan = paragraph_span((i,j), text)
    print(f"""{Fore.CYAN+Style.BRIGHT}Need Rotten Tomatoes ID for a match in [[{title}]].{Style.RESET_ALL}
{Fore.GREEN+Style.BRIGHT}Context------------------------------------------{Style.RESET_ALL}
{text[pspan[0]: i] + Style.BRIGHT + text[i: j] + Style.RESET_ALL + text[j: pspan[1]]}
{Fore.GREEN+Style.BRIGHT}-------------------------------------------------{Style.RESET_ALL}""")

    prompt = 'Enter Rotten Tomatoes ID (or open in [b]rowser, [s]kip, or [q]uit): '
    while not re.fullmatch(r'm/[-a-z0-9_]+', (user_input:=input(prompt)) ):
        if user_input == 'b':
            webbrowser.open(Page(Site('en','wikipedia'), title).full_url())
        elif user_input == 's':
            print(f"Skipping match."); return None
        elif user_input == 'q':
            print("Quitting program."); sys.exit()
        else:
            print("ID must match the regex 'm/[-a-z0-9_]+'.")
    return user_input

def _ask_for_qid(cand, rtmatch):
    title, text = cand.title, cand.text
    rtid = rtmatch.movie.short_url
    print(f"""{Fore.CYAN+Style.BRIGHT}Need QID for Rotten Tomatoes ID {rtid}.{Style.RESET_ALL}""")

    prompt = 'Enter QID (or open in [b]rowser, [s]kip, or [q]uit): '
    while not re.fullmatch(r'Q[0-9]+', (user_input:=input(prompt)) ):
        if user_input == 'b':
            webbrowser.open(scraper.rt_url(rtid))
        elif user_input == 's':
            print(f"Skipping match."); return None
        elif user_input == 'q':
            print("Quitting program."); sys.exit()
        else:
            print("QID must match the regex 'Q[0-9]+'.")
    return user_input


# ===========================================================================================
def _find_span333(match, title):
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
    #text = text[:matchstart] + text[matchstart: para_end].replace('\n',' ') + text[para_end:]

    p4 = re.compile(r'(?:([.!][ \']?"|(?<![A-Z])[.!])((\s*[@`]+)+|(?=\s+[^a-z]))|}}\s*@+|\n)\s*', flags=re.REVERSE)
    i = p4.search(text, 0, matchstart+1).end()

    p5 = re.compile(r'([.!][ \']?"|(?<![A-Z])[.!])((\s*[@`]+)+|(?=\s+[^a-z]))|}}\s*@+|(?=\n\n|\n==)')
    j = p5.search(text, pos=rindex_pattern(r'\w', text, 0, match.end())).end()

    #print(match.string[i:j])
    return (i, j)


def _p1258(title):
    with WIKIDATA_LOCK:
        item = ItemPage.fromPage(Page(Site('en','wikipedia'), title))
        if 'P1258' in item.claims:
            z = item.claims['P1258'][0].getTarget()
            if z.startswith('m/'):
                return z
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
        movieid = "m/" + parse_template(citert)[1]['id']
    elif rt := m['rt']:
        d = parse_template(rt)[1]
        if '1' in d:
            movieid = d['1']
        elif 'id' in d:
            movieid = d['id']
        else:
            movieid = _p1258(title)
            if movieid is None:
                return None, None
        if not movieid.startswith('m/'):
            movieid = 'm/' + movieid
    return ref, movieid.lower()

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
    print_logger.info(f"GOOGLING ID for [[{title}]].")
    with GOOGLESEARCH_LOCK:
        time.sleep(5)      # avoid getting blocked, better safe than sorry
        url = lucky(title+' movie site:rottentomatoes.com/m/',
            user_agent=scraper.USER_AGENT)
    suggested_id = url.split('rottentomatoes.com/m/')[1]
    return 'm/' + suggested_id.split('/')[0]

def _find_RTMovie(page, initial_id, make_guess = False):
    try:
        if initial_id:
            return scraper.RTMovie(initial_id)
    except Exception:
        pass

    if not make_guess:
        return None

    if (p := _p1258(page.title)) and p != initial_id:
        try:
            return scraper.RTMovie(p)
        except Exception:
            pass

    def probably_correct():
        lead = page.text[:page.text.index('\n==')]
        names = chain.from_iterable(name.split() for name in movie.director+movie.writer)
        checkwords = [x for x in names if x[-1] != '.']+[' '+movie.year]
        # print(checkwords)
        if any(x not in lead for x in checkwords):
            return False
        if f"'''''{movie.title}'''''" in lead:
            return True
        if not f"''{movie.title}''" in lead:
            return False
        z = re.findall(r'\d+', movie.runtime)
        if len(z) == 1:
            hours, minutes = 0, int(z[0])
        else:
            hours, minutes = map(int, z)
        return f'{60*hours + minutes} minutes' in lead

    try:
        movie = scraper.RTMovie(googled_id(page.title))
    except Exception:
        pass
    else:
        if probably_correct():
            return movie
    return None


if __name__ == "__main__":
    pass


