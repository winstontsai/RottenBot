# This module takes Candidates and computes the new text to be used.
################################################################################
import re
import sys
import webbrowser
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
    s += f"{{{{Cite web|url={url}|title={title} ({year})|website=[[Rotten Tomatoes]]|publisher=[[Fandango Media]]|access-date={access_date}}}}}</ref>"
    #s += f"{{{{Cite Rotten Tomatoes |id={d['id']} |type=movie |title={d['title']} |access-date={d['accessDate']}}}}}</ref>"
    return s

@dataclass
class Edit:
    title: str
    replacements: list[tuple[str, str]]
    flags: list[str]

def compute_edits(candidates, get_user_input = True):
    """
    The candidates parameter should be
    an iterable of candidate objects.
    """
    all_edits = []
    for cand in candidates:
        if e := compute_edit_list(cand):
            all_edits.append(e)
    return all_edits


def compute_edit_list(cand):
    edits = []
    text = cand.text
    for rtmatch in cand.matches:
        span, rt_data, flags = rtmatch.span, rtmatch.rt_data, []

        if rt_data is None or rt_data.tomatometer_score is None:
            return None
        score, count, average = rt_data.tomatometer_score
        rating_prose, consensus_prose = rating_and_consensus_prose(rt_data)

        old_prose, refs = text[span[0]:span[1]], text[span[1]:span[2]]

        if refs.count('<ref') > 1:
            flags.append("multiple references")

        if refs[-1] == '.':
            flags.append('period after reference')

        # check for some suspicious characters
        if old_prose[0] not in "[{'ABCGIORTW1234567890":
            flags.append("suspicious start")

        if old_prose[-1] not in '."}' and refs[-1]!='.' and text[span[2]]!='\n':
            flags.append("suspicious end")

        # audience score?
        if 'audience' in old_prose:
            flags.append("audience")

        # we will update/build up new_prose step by step
        new_prose = old_prose

        # First deal with the template {{Rotten Tomatoes prose}}
        if m := re.match(t_rtprose, new_prose):
            temp_dict = {
                '1': score,
                '2': average,
                '3': count,
            }
            new_prose = construct_template('Rotten Tomatoes prose', temp_dict)
        else:
            # NOWHERE DOES IT SAY IT'S A WEIGHTED AVERAGE
            new_prose = re.sub(r'\[\[[wW]eighted.*?\]\]', 'average rating', new_prose)
            new_prose = re.sub(r'weighted average( rating| score)?', 'average rating', new_prose)
            new_prose = new_prose.replace(' a average', ' an average')
            if re.search("[wW]eighted", new_prose):
                new_prose = rating_prose

            # Update {{As of}} template, if it exists.
            # Otherwise remove as of prose
            if m:=re.search(t_asof, new_prose):
                old_temp = m.group()
                temp_dict = parse_template(old_temp)[1]
                day, month, year = date.today().strftime("%d %m %Y").split()
                temp_dict['1'] = year
                temp_dict['2'] = month
                if '3' in temp_dict:
                    temp_dict['3'] = day
                new_temp = construct_template("As of", temp_dict)
                new_prose = new_prose.replace(old_temp, new_temp)
            elif re.search("[Aa]s of", new_prose):
                new_prose = rating_prose

            # handle average rating     
            new_prose, k = re.subn(average_re, f'{average}/10', new_prose)
            if k == 0:
                new_prose = rating_prose
            elif k > 1:
                flags.append("multiple averages")
                
            # handle review reviewCount
            new_prose, k = re.subn(count_re, f"{count} \g<count_term>", new_prose)
            if k == 0:
                new_prose = rating_prose
            elif k > 1:
                flags.append("multiple counts")

            # handle score
            all_scores = [m.group('score') for m in re.finditer(score_re, old_prose)]
            if len(all_scores) > 1:
                if set(all_scores) not in ({'0'}, {'100'}):
                    flags.append("multiple scores")
                elif score != all_scores[0]:
                    flags.append("multiple scores")
            new_prose= re.sub(score_re, score + '%', new_prose)

        # add consensus if safe
        p_start = text.rfind('\n', 0, span[0])
        p_end = text.find('\n', span[2]) #paragraph end
        if (rt_data.consensus and
                'consensus' not in text[p_start:span[0]]+new_prose+text[span[2]:p_end] and
                (len(cand.matches)==1 or span[0]>text.find('==') )):
            new_prose += " " + consensus_prose

        # fix period/quote situation
        if new_prose.endswith('.".'):
            new_prose = new_prose[:-1]
        elif new_prose.endswith('".'):
            new_prose = new_prose[:-2] + '."'

        # if no change, don't produce an edit
        if new_prose == old_prose:
            return None

        # create replacements list
        replacements = [(old_prose, new_prose)]
        ref = rtmatch.ref
        if ref.list_defined:
            replacements.append((refs, f'<ref name="{ref.name}" />'))
            replacements.append((ref.text, citation_replacement(rtmatch)))
        else:
            replacements.append((refs, citation_replacement(rtmatch)))

        edits.append(Edit(cand.title, replacements, flags))

    return edits if edits else None


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








