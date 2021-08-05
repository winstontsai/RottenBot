# This module takes Candidates and computes replacement text.
################################################################################
import re
import sys
import webbrowser
import string
import logging
logger = logging.getLogger(__name__)
print_logger = logging.getLogger('print_logger')

from dataclasses import dataclass, field
from datetime import date

import pywikibot as pwb

from patterns import *
################################################################################

def rating_and_consensus_prose(rt_data):
    title = rt_data.title
    score, count, average = rt_data.tomatometer_score
    consensus = rt_data.consensus
    s = (f"On [[Rotten Tomatoes]], ''{title}'' holds an approval rating " +
f"of {score}% based on {count} reviews, with an average rating of {average}/10.")
    if consensus or int(count)>=20:
        s = s.replace('approval rating of 100%', '[[List of films with a 100% rating on Rotten Tomatoes|approval rating of 100%]]')
        s = s.replace('approval rating of 0%', '[[List of films with a 0% rating on Rotten Tomatoes|approval rating of 0%]]')
    return s, f'The site\'s critical consensus reads, "{consensus}"'

def citation_replacement(rtmatch):
    refname = rtmatch.ref.name
    m = rtmatch.rt_data
    url, title, year, access_date = m.url, m.title, m.year, m.access_date
    s = "<ref"
    if refname:
        s += f' name="{refname}">'
    else:
        s += '>'
    s += f"{{{{Cite web|url={url}|title={title} ({year})|website=[[Rotten Tomatoes]]|publisher=[[Fandango Media|Fandango]]|access-date={access_date}}}}}</ref>"
    #s += f"{{{{Cite Rotten Tomatoes |id={d['id']} |type=movie |title={d['title']} |access-date={d['accessDate']}}}}}</ref>"
    return s

@dataclass
class Edit:
    title: str
    replacements: list[tuple[str, str]]
    flags: frozenset[str]

def disqualifying(flags):
    """
    Return True if the flags disqualify an edit from being made automatically
    without human review.
    """
    if not flags:
        return False
    if flags == {'multiple counts'}:
        return False
    return True

def compute_edits(candidates, get_user_input = True):
    """
    The candidates parameter should be
    an iterable of candidate objects.
    """
    all_edits = dict()
    for cand in candidates:
        if e := compute_edit_list(cand):
            all_edits[cand.title] = e
    return all_edits


def compute_edit_list(cand):
    edits = []
    text = cand.text
    for rtmatch in cand.matches:
        if rtmatch.rt_data is None or rtmatch.rt_data.tomatometer_score is None:
            continue

        span, rt_data, flags = rtmatch.span, rtmatch.rt_data, set()
        score, count, average = rt_data.tomatometer_score
        rating_prose, consensus_prose = rating_and_consensus_prose(rt_data)

        old_text = text[span[0]:span[1]]
        old_prose = text[span[0]:span[1]]

        # delete comments
        old_text = re.sub(r'<!--.*?-->', '', old_text, flags=re.DOTALL)
        old_prose = re.sub(r'<!--.*?-->', '', old_prose, flags=re.DOTALL)
        # use straight quotes
        old_prose = old_prose.translate(str.maketrans('“”','""'))

        if len(old_text) > 800:
            flags.add('long')

        if pattern_count(r'[mM]etacritic', old_prose):
            flags.add("Metacritic")

        prose_without_refs = re.sub(r'<ref.+?(/>|/ref)', '', old_text, flags=re.DOTALL)
        if (pattern_count('Rotten Tomatoes', prose_without_refs)
                - pattern_count(r'ilms with a (?:100|0)% rating on Rotten', prose_without_refs)) > 1:
            flags.add('multiple Rotten Tomatoes')

        if old_text.count('<ref') > 1:
            flags.add("multiple references")

        if old_text[-1] == '.':
            flags.add('period after reference')

        # check for some suspicious characters
        if old_prose[0] not in string.ascii_uppercase + string.digits + "'{[":
            flags.add("suspicious start")

        def bad_end():
            return (
                old_prose[-1] not in '."' and
                old_text[-1] != '.' and
                text[span[1]:span[1]+2] != '\n\n' and
                not re.match(t_rtprose, old_prose)
            )

        if bad_end():
            flags.add("suspicious end")

        # audience score?
        prose_minus_quotes = re.sub(r'".+?"', '', old_prose, flags=re.DOTALL)
        if pattern_count(r'\b(?:[aA]udience|[uU]ser)|[vV]iewer', prose_minus_quotes):
            flags.add('audience|user|viewer')

        #######################################################################
        # we will update/build up new_prose step by step
        new_prose = old_prose

        # First deal with the template {{Rotten Tomatoes prose}}
        if m := re.match(t_rtprose, new_prose):
            temp_dict = {
                '1': score,
                '2': average,
                '3': count,
            }
            new_prose = new_prose.replace(m.group(), construct_template('Rotten Tomatoes prose', temp_dict)) 
        else:
            # NOWHERE DOES IT SAY IT'S A WEIGHTED AVERAGE
            new_prose = re.sub(r'\[\[[wW]eighted.*?\]\]', 'average rating', new_prose)
            new_prose = re.sub(r'weighted average( rating| score)?', 'average rating', new_prose)
            new_prose = new_prose.replace(' a average',' an average').replace('rating rating','rating')
            if re.search("[wW]eighted", new_prose):
                new_prose = rating_prose

            # handle average rating     
            new_prose, k = re.subn(average_re, f'{average}/10', new_prose)
            if k == 0:
                new_prose = rating_prose
            elif k > 1:
                flags.add("multiple averages")
                
            # handle review reviewCount
            new_prose, k = re.subn(count_re, f"{count} \g<count_term>", new_prose)
            if k == 0:
                new_prose = rating_prose
            elif k > 1:
                flags.add("multiple counts")

            # handle score
            all_scores = [m.group(1) for m in re.finditer(score_re, old_prose)]
            if len(all_scores) > 1:
                if set(all_scores) not in ({'0'}, {'100'}):
                    flags.add("multiple scores")
                elif score != all_scores[0]:
                    flags.add("multiple scores")
            if "multiple scores" in flags:
                new_prose = rating_prose
            else:
                new_prose= re.sub(score_re, score + '%', new_prose)

        if flags == {'multiple counts'}:
            new_prose = rating_prose

        # if new_prose == rating_prose:
        #     flags.add('default replacement')

        # add consensus if safe
        def safe_to_add_consensus():
            if not rt_data.consensus:
                return False
            p_start = text.index('\n\n', 0, span[0])  #paragraph start
            p_end = text.index('\n\n', span[1])        #paragraph end
            s = text[p_start:span[0]]+new_prose+text[span[1]:p_end]
            s_l = ''.join(x for x in s if x in string.ascii_letters)
            c_l = ''.join(x for x in rt_data.consensus if x in string.ascii_letters)

            if not pattern_count('[cC]onsensus', s) and c_l in s_l:
                print("CONTAINS CONSENSUS BUT NO WORD 'CONSENSUS'!!!!!!!!!!!!!!!!!!!!!!!")

            if pattern_count('[cC]onsensus', s):
                return False
            if len(cand.matches)>1 and span[0]<text.find('=='):
                return False

            if c_l in s_l:
                return False
            return True
        if safe_to_add_consensus():
            new_prose += ' ' + consensus_prose

        # fix period/quote situation
        if new_prose.endswith('.".'):
            new_prose = new_prose[:-1]
        elif new_prose.endswith('".'):
            new_prose = new_prose[:-2] + '."'

        # if no change, don't produce an edit
        if new_prose == old_prose:
            continue

        # Update "As of"
        if m:=re.search(t_asof, new_prose): # As of template
            old_temp = m.group()
            day, month, year = date.today().strftime("%d %m %Y").split()
            temp_dict = parse_template(old_temp)[1]
            temp_dict['1'], temp_dict['2'] = year, month
            if '3' in temp_dict:
                temp_dict['3'] = day
            new_temp = construct_template("As of", temp_dict)
            new_prose = new_prose.replace(old_temp, new_temp)
        elif m:=re.search(r"[Aa]s of (?=January|February|March|April|May|June|July|August|September|October|November|December|[1-9])[ ,a-zA-Z0-9]{,14}[0-9]{4}(?![0-9])", new_prose):
            old_asof = m.group()
            day, month, year = date.today().strftime("%d %B %Y").split()
            new_date = month + ' ' + year
            if pattern_count(r'[0-9]', old_asof) > 4: # if includes day
                if old_asof[6] in string.digits: # begins with day num
                    new_date = f'{day} {month} {year}'
                else:
                    new_date = f'{month} {day}, {year}'
            new_asof = old_asof[:6] + new_date
            new_prose = new_prose.replace(old_asof, new_asof)
        elif re.search(r"\b[Aa]s of\b", new_prose):
            new_prose = rating_prose

        # add reference stuff
        ref = rtmatch.ref
        if ref.list_defined:
            new_text = new_prose + f'<ref name="{ref.name}" />'
        else:
            new_text = new_prose + citation_replacement(rtmatch)

        # create replacements list
        replacements = [(text[span[0]:span[1]], new_text)]
        if ref.list_defined:
            replacements.append((ref.text, citation_replacement(rtmatch)))

        edits.append(Edit(cand.title, replacements, frozenset(flags)))

    return edits

def make_replacements(edit_list):
    site = pwb.Site('en', 'wikipedia')
    not_edited = list()
    for edit in edit_list:
        page = pwb.Page(site, edit.title)
        for old, new in edit.replacements:
            if old in page.text:
                page.text = page.text.replace(old, new)
            else:
                not_edited.append(edit.title)
                break
        else:
            page.save()
    return not_edited



if __name__ == "__main__":
    pass






