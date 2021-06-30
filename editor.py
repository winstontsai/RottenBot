# This module takes Candidates and computes the new text to be used.

import re
import sys
import webbrowser
import logging

from dataclasses import dataclass


import pywikibot as pwb

from patterns import *

def rating_prose(cand):
    d = cand.rt_data
    s = ("On review aggregator [[Rotten Tomatoes]], the film holds an approval rating " +
f"of {d['score']}% based on {d['reviewCount']} reviews, with an average rating of {d['average']}/10.")
    if d['consensus'] or int(d['reviewCount'])>=20:
        s = s.replace('approval rating of 100%', '[[List of films with a 100% rating on Rotten Tomatoes|approval rating of 100%]]')
        s = s.replace('approval rating of 0%', '[[List of films with a 0% rating on Rotten Tomatoes|approval rating of 0%]]')
    return s

def consensus_prose(cand):
    d = cand.rt_data
    return f'The website\'s critical consensus reads, "{d["consensus"]}"'

def citation_replacement(cand):
    d, refname = cand.rt_data, cand.ref.refname
    s = "<ref"
    if refname:
        s += f' name="{refname}">'
    else:
        s += '>'
    s += f"{{{{Cite web|url={d['url']}|title={d['title']}|website=[[Rotten Tomatoes]]|publisher=[[Fandango Media]]|access-date={d['accessDate']}}}}}</ref>"
    #s += f"{{{{Cite Rotten Tomatoes |id={d['id']} |type=movie |title={d['title']} |access-date={d['accessDate']}}}}}</ref>"
    return s

@dataclass
class Edit:
    title: str
    replacements: list[tuple[str, str]]
    flags: list[str]

def compute_edits(candidates, get_user_input = True):
    for cand in candidates:
        if e := compute_edit(cand):
            yield e

def compute_edit(cand):
    rt_data = cand.rt_data

    span, pagetext, flags = cand.span, cand.pagetext, list()

    # ignore reference for now
    old_prose = pagetext[span[0] : span[1]]

    # we will update/build up new_prose step by step
    new_prose = old_prose

    if cand.prose.count('<ref') > 1:
        flags.append("multiple refs")

    # check for some suspicious characters
    if old_prose[0] not in "[{'ABCGIORTW1234567890":
        flags.append("suspicious start")

    if old_prose[-1] not in '."}' and cand.prose[-1] != '.' and pagetext[span[2]] != '\n':
        flags.append("suspicious end")

    # First deal with template {{Rotten Tomatoes prose}}
    if m := re.match(t_rtprose, new_prose):
        temp_dict = {
            1: rt_data["score"],
            2: rt_data["average"],
            3: rt_data["reviewCount"],
        }
        new_prose = construct_template('Rotten Tomatoes prose', temp_dict)
    else:
        # NOWHERE DOES IT SAY IT'S A WEIGHTED AVERAGE
        new_prose = re.sub(r'\[\[[wW]eighted.*?\]\]', 'average rating', new_prose)
        new_prose = re.sub(r'weighted average( rating| score)?', 'average rating', new_prose)
        new_prose = new_prose.replace(' a average', ' an average')
        if re.search("[wW]eighted", new_prose):
            new_prose = rating_prose(cand)

        # Remove as of date
        if re.search("[Aa]s ?of", new_prose):
            new_prose = rating_prose(cand)

        # handle average rating     
        new_prose, k = re.subn(average_re, f'{rt_data["average"]}/10', new_prose)
        if k == 0:
            new_prose = rating_prose(cand)
        elif k > 1:
            flags.append("multiple averages")
            
        # handle review reviewCount
        new_prose, k = re.subn(count_re, f"{rt_data['reviewCount']} \g<count_term>", new_prose)
        if k == 0:
            new_prose = rating_prose(cand)
        elif k > 1:
            flags.append("multiple counts")

        # handle score
        all_scores = [m.group('score') for m in re.finditer(score_re, old_prose)]
        if len(all_scores) > 1:
            if set(all_scores) not in ({'0'}, {'100'}):
                flags.append("multiple scores")
            elif rt_data['score'] != all_scores[0]:
                flags.append("multiple scores")
        new_prose= re.sub(score_re, rt_data['score']+'%', new_prose)


    # add consensus if safe
    if (rt_data["consensus"]
            and ' consensus' not in new_prose
            and not re.match('[^\n]* consensus', pagetext[span[2]: ]) ):
        new_prose += " " + consensus_prose(cand)

    # fix period/quote situation
    if new_prose.endswith('.".'):
        new_prose = new_prose[:-1]
    elif new_prose.endswith('".'):
        new_prose = new_prose[:-2] + '."'

    # if no change, don't produce an edit
    if new_prose == old_prose:
        return None

    # add reference and create replacements list
    if cand.ref.ld: # list-defined reference requires two replacements
        new_prose += f'<ref name="{cand.ref.refname}" />'
        replacements = [(cand.prose, new_prose),
                        (cand.ref.reftext, citation_replacement(cand))]
    else:
        new_prose += citation_replacement(cand)
        replacements = [(cand.prose, new_prose)]

    return Edit(cand.title, replacements, flags)


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








