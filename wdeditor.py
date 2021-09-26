# This module is for editing Rotten Tomatoes scores on Wikidata.
###############################################################################
import json
import sys
import time

from datetime import date

import pywikibot as pwb
import pywikibot.data.sparql as sparql
import regex as re

from pywikibot import Claim, ItemPage, Site

from scraper import RTMovie, USER_AGENT
################################################################################
SITE = Site('wikidata', 'wikidata')

Q_ROTTEN_TOMATOES           = 'Q105584'
Q_TOMATOMETER               = 'Q108403393'
Q_ROTTEN_TOMATOES_AVERAGE   = 'Q108403540'
Q_FANDANGO                  = 'Q5433722'
Q_ENGLISH                   = 'Q1860'

P_ROTTEN_TOMATOES_ID        = 'P1258'
P_REVIEW_SCORE              = 'P444'
P_REVIEW_SCORE_BY           = 'P447'
P_REVIEW_COUNT              = 'P7887'
P_POINT_IN_TIME             = 'P585'
P_DETERMINATION_METHOD      = 'P459'
P_REFERENCE_URL             = 'P854'
P_RETRIEVED                 = 'P813'
P_TITLE                     = 'P1476'
P_PUBLISHER                 = 'P123'
P_LANGUAGE                  = 'P407'
P_STATED_IN                 = 'P248'
P_REASON_FOR_PREFERRED_RANK = 'P7452'
P_REASON_FOR_DEPRECATION    = 'P2241'
P_NAMED_AS                  = 'P1810'

def make_claim(pid, target):
    """
    Return pwb.Claim object for entity with pid and specified target.
    """
    c = Claim(SITE, pid)
    c.setTarget(target)
    return c

def make_item(qid):
    return ItemPage(SITE, qid)

def get_results(query):
    headers = dict(sparql.DEFAULT_HEADERS)
    headers['User-Agent'] = USER_AGENT
    data = sparql.SparqlQuery().query(query, headers)
    return data['results']['bindings']

class RTID_to_QID:
    def __init__(self):
        query = "SELECT ?item ?itemLabel ?rtid WHERE{?item wdt:P1258 ?rtid.FILTER REGEX(?rtid, '^m/')}"
        data = dict()
        for z in get_results(query):
            qid = z['item']['value'].split('/')[-1]
            rtid = z['rtid']['value'].lower()
            data[rtid] = qid
        self.data = data

    def __getitem__(self, rtid):
        return self.data.get(rtid, None)

    def __setitem__(self, rtid, value):
        if type(rtid) != str or type(value) != str:
            return
        if not re.fullmatch('m/[-a-z0-9_]+', rtid) or not re.fullmatch('Q[0-9]+', value):
            return
        self.data[rtid] = value

def date_from_claim(c):
    """
    Returns "point in time" date, otherwise "retrieved" date, otherwise
    date(1, 1, 3) if the rank is preferred, and date(1,1,2) if rank is normal,
    date(1, 1, 1) if rank is deprecated
    """
    q = c.qualifiers
    if P_POINT_IN_TIME in q:
            wbtime = q[P_POINT_IN_TIME][0].target
            y, m, d = wbtime.year or 1, wbtime.month or 1, wbtime.day or 1
            return date(y, m, d)

    if c.sources:
        retrieved = c.sources[0].get(P_RETRIEVED)
        if retrieved:
            wbtime = retrieved[0].target
            y, m, d = wbtime.year or 1, wbtime.month or 1, wbtime.day or 1
            return date(y, m, d)

    if c.rank == 'preferred':
        return date(1, 1, 3)
    if c.rank == 'normal':
        return date(1, 1, 2)
    return date(1, 1, 1)

def most_recent_score_data(item):
    # item.purge()
    # item.get(force=True)
    score, count, average = '', '', ''
    newest_date = date(1,1,1)
    for c in item.claims.get(P_REVIEW_SCORE, []):
        q = c.qualifiers
        if c.rank == 'deprecated' or c.snaktype != 'value':
            continue
        if P_REVIEW_COUNT not in q or P_DETERMINATION_METHOD not in q:
            continue
        if q[P_DETERMINATION_METHOD][0].target.getID() != Q_TOMATOMETER:
            continue

        if (review_date := date_from_claim(c)) >= newest_date:
            newest_date = review_date
            score = c.target
            count = str(q[P_REVIEW_COUNT][0].target.amount)

    # find corresponding average rating, if it exists
    if score:
        for c in item.claims.get(P_REVIEW_SCORE, []):
            q = c.qualifiers
            if c.rank == 'deprecated' or c.snaktype != 'value':
                continue
            if P_DETERMINATION_METHOD not in q:
                continue
            if q[P_DETERMINATION_METHOD][0].target.getID() != Q_ROTTEN_TOMATOES_AVERAGE:
                continue

            if date_from_claim(c) == newest_date:
                average = c.target
                break

    return score, count, average
    

def should_add_RT_claims(movie, item):
    """
    If should add RT claims, return the two claims (percent and average)
    to be added.
    Otherwise return False.
    """
    if not movie.tomatometer_score:
        return False
    new_score, new_count, new_average = movie.tomatometer_score
    new_score = int(new_score)
    new_count = int(new_count)
    if new_average:
        new_average = float(new_average)

    old_score, old_count, old_average = most_recent_score_data(item)
    #print(old_score, old_count, old_average)
    if not old_score:
        return score_claims_from_movie(movie)

    if m := re.fullmatch(r'([0-9]|[1-9][0-9]|100)(%| percent)', old_score):
        old_score = int(m[1])
    else:
        return score_claims_from_movie(movie)

    if re.fullmatch(r'\d+', old_count):
        old_count = int(old_count)
    else:
        return score_claims_from_movie(movie)
    
    if old_average:
        if m := re.fullmatch(r'(([0-9]|10)(\.\d\d?)?)(?:/| out of )10', old_average):
            old_average = float(m[1])
        else:
            return score_claims_from_movie(movie)

    if (old_score, old_count, old_average) != (new_score, new_count, new_average):
        return score_claims_from_movie(movie)
    return False

def score_claims_from_movie(movie):
    """
    Assuming that movie has tomatometer_score.
    """
    score, count, average = movie.tomatometer_score
    # manage average format
    if average == '': # in rare cases, no average is available
        pass
    elif '00' in average:
        average = average[0] + '/10'
    else:
        average = str(float(average)) + '/10'

    percent_claim = make_claim(P_REVIEW_SCORE, score + '%')
    average_claim = make_claim(P_REVIEW_SCORE, average)

    # set up qualifiers
    RTitem = make_item(Q_ROTTEN_TOMATOES)
    d, m, y = map(int, date.today().strftime('%d %m %Y').split())
    wbtimetoday = pwb.WbTime(y, m, d, site = SITE)
    review_score_by = make_claim(P_REVIEW_SCORE_BY, RTitem)
    review_quantity = pwb.WbQuantity(amount=count,
        unit="http://www.wikidata.org/entity/Q80698083", # unit = critic review
        site=SITE
    )
    number_of_reviews = make_claim(P_REVIEW_COUNT, review_quantity)
    point_in_time = make_claim(P_POINT_IN_TIME, wbtimetoday)
    percent_method = make_claim(P_DETERMINATION_METHOD, make_item(Q_TOMATOMETER))
    average_method = make_claim(P_DETERMINATION_METHOD, make_item(Q_ROTTEN_TOMATOES_AVERAGE))
    
    # set up reference
    statedin = make_claim(P_STATED_IN, RTitem)
    rtid_claim = make_claim(P_ROTTEN_TOMATOES_ID, movie.short_url)
    title = make_claim(P_TITLE, pwb.WbMonolingualText(movie.title, 'en'))
    languageofwork = make_claim(P_LANGUAGE, make_item(Q_ENGLISH))
    retrieved = make_claim(P_RETRIEVED, wbtimetoday)
    source_order = [statedin, rtid_claim, title, retrieved]

    # add qualifiers, reference, and rank for percent claim
    for x in [review_score_by, number_of_reviews, point_in_time, percent_method]:
        percent_claim.addQualifier(x)
    percent_claim.addSources(source_order)
    percent_claim.setRank('normal')

    # add qualifiers, reference, and rank for average claim
    for x in [review_score_by, point_in_time, average_method]:
        average_claim.addQualifier(x)
    average_claim.addSources(source_order)
    average_claim.setRank('normal')

    if average == '': # special case when there is percent but no average
        average_claim.setSnakType('novalue')

    return percent_claim, average_claim

def add_RT_claims_to_item(movie, item):
    if z := should_add_RT_claims(movie, item):
        percent_claim, average_claim = z
    else:
        return False

    # set rank of all existing non-deprecated RT score claims to 'normal'
    for c in item.claims.get(P_REVIEW_SCORE, []):
        if P_REVIEW_SCORE_BY in c.qualifiers: # review by
            val = c.qualifiers[P_REVIEW_SCORE_BY][0].target
            if val == make_item(Q_ROTTEN_TOMATOES) and c.rank == 'preferred':
                c.changeRank('normal')

    item.addClaim(percent_claim, summary='Add Rotten Tomatoes score. Test edit. See [[Wikidata:Requests for permissions/Bot/RottenBot]].')
    item.addClaim(average_claim, summary='Add Rotten Tomatoes average rating. Test edit. See [[Wikidata:Requests for permissions/Bot/RottenBot]].')
    return True

def add_RTmovie_data_to_item(movie, item):
    """
    Adds/updates the Rotten Tomatoes data in a Wikidata item.
    Currently this means the Rotten Tomatoes ID and the two score claims.
    """
    print(f"Checking item {item.getID()} aka {item.labels.get('en')}.")
    changed = False
    title = movie.title

    if 'en' not in item.labels:
        item.editLabels( {'en': title}, summary=f'Add English label {title}. Test edit. See [[Wikidata:Requests for permissions/Bot/RottenBot]].')
    current_label = item.labels['en']

    # different language?
    titlediff = title.lower() != current_label.lower()
    current_aliases = item.aliases.get('en', [])
    if titlediff and title not in (s.lower() for s in current_aliases):
        item.editAliases( {'en': current_aliases+[title]}, summary=f'Add alias {title}. Test edit. See [[Wikidata:Requests for permissions/Bot/RottenBot]].')

    # check if up-to-date Rotten Tomatoes ID exists, add if it does not.
    # also add P_NAMED_AS qualifier if the RT title is different from the label
    for claim in item.claims.get(P_ROTTEN_TOMATOES_ID, []):
        if claim.target == movie.short_url:
            if titlediff:
                if P_NAMED_AS not in claim.qualifiers:
                    claim.addQualifier(make_claim(P_NAMED_AS, title), summary='Add "named as" qualifier to Rotten Tomatoes ID claim. Test edit. See [[Wikidata:Requests for permissions/Bot/RottenBot]].')
                    changed = True
                elif claim.qualifiers[P_NAMED_AS][0].target != title:
                    claim.removeQualifier(claim.qualifiers[P_NAMED_AS][0])
                    claim.addQualifier(make_claim(P_NAMED_AS, title), summary='Add "named as" qualifier to Rotten Tomatoes ID claim. Test edit. See [[Wikidata:Requests for permissions/Bot/RottenBot]].')
                    changed = True
            break
    else:
        d, m, y = map(int, date.today().strftime('%d %m %Y').split())
        retrieved = make_claim(P_RETRIEVED, pwb.WbTime(y, m, d, site=SITE))
        rtid_claim = make_claim(P_ROTTEN_TOMATOES_ID, movie.short_url)
        rtid_claim.addSource(retrieved)
        if titlediff:
            rtid_claim.addQualifier(make_claim(P_NAMED_AS, title))
        item.addClaim(rtid_claim)
        changed = True

    if add_RT_claims_to_item(movie, item):
        changed = True

    if changed:
        print(f"Updated item {item.getID()} aka {item.labels.get('en')}.")
    return changed


def update_film_items(id_pairs, limit = 1):
    """
    id_pairs should be list of (qid, rtid) pairs.
    """
    j = 0
    for qid, rtid in id_pairs:
        #print(limit, j)
        try:
            movie = RTMovie(rtid)
        except Exception:
            print(f'Item {qid} has invalid RTID {rtid}.')
            continue

        j += add_RTmovie_data_to_item(movie, make_item(qid))
        if j >= limit:
            break
    return j

# class FilmTypes:
#     film_types = None

#     @classmethod
#     def has_film_type(cls, item):
#         if cls.film_types is None:
#             query = "SELECT ?ft WHERE {?ft wdt:P279* wd:Q11424}"
#             cls.film_types = set(r['ft']['value'].split('/')[-1] for r in get_results(query))
#         for c in item.claims.get('P31', []):
#             if hasattr(c.target, 'getID') and c.target.getID() in cls.film_types:
#                 return True
#         return False


if __name__ == "__main__":
    SITE.login()

    pairs = [('Q2201', 'm/1217700-kick_ass')]
    update_film_items(pairs)



