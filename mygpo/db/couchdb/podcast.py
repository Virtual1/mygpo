from hashlib import sha1
from datetime import datetime

from restkit import RequestFailed
from couchdbkit import MultipleResultsFound

from django.core.cache import cache

from mygpo.core.models import Podcast, PodcastGroup, PodcastSubscriberData
from mygpo.core.signals import incomplete_obj
from mygpo.decorators import repeat_on_conflict
from mygpo.cache import cache_result
from mygpo.utils import get_timestamp
from mygpo.db.couchdb import get_main_database, get_userdata_database, \
    lucene_query
from mygpo.db import QueryParameterMissing
from mygpo.db.couchdb import get_main_database, get_single_result
from mygpo.db.couchdb.utils import multi_request_view, is_couchdb_id

import logging
logger = logging.getLogger(__name__)


def podcasts_groups_by_id(ids):
    """ gets podcast groups and top-level podcasts for the given ids """

    if ids is None:
        raise QueryParameterMissing('ids')

    if not ids:
        return

    db = get_main_database()
    res = db.view('podcasts/podcasts_groups',
            keys         = ids,
            include_docs = True,
        )

    for r in res:
        obj = _wrap_pg(r)

        if not obj:
            yield None
            continue

        if obj.needs_update:
            incomplete_obj.send_robust(sender=obj)

        yield obj


def _wrap_pg(doc):

    doc = doc['doc']

    if not doc:
        return None

    if doc['doc_type'] == 'Podcast':
        return Podcast.wrap(doc)

    elif doc['doc_type'] == 'PodcastGroup':
        return PodcastGroup.wrap(doc)

    else:
        logger.error('received unknown doc_type "%s"', doc['doc_type'])


def podcasts_to_dict(ids, use_cache=False):

    if ids is None:
        raise QueryParameterMissing('ids')

    if not ids:
        return dict()


    ids = list(set(ids))
    objs = dict()

    cache_objs = []
    if use_cache:
        res = cache.get_many(ids)
        cache_objs.extend(res.values())
        ids = [x for x in ids if x not in res.keys()]

    from mygpo.podcasts.models import Podcast
    db_objs = Podcast.objects.filter(id__in=ids)

    for obj in (cache_objs + db_objs):

        # get_multi returns dict {'key': _id, 'error': 'not found'}
        # for non-existing objects
        if isinstance(obj, dict) and 'error' in obj:
            _id = obj['key']
            objs[_id] = None
            continue

        for i in obj.get_ids():
            objs[i] = obj

    if use_cache:
        cache.set_many(dict( (obj.get_id(), obj) for obj in db_objs))

    return objs


def subscriberdata_for_podcast(podcast_id):

    if not podcast_id:
        raise QueryParameterMissing('podcast_id')

    db = get_main_database()
    data = get_single_result(db, 'podcasts/subscriber_data',
            key          = podcast_id,
            include_docs = True,
            schema       = PodcastSubscriberData,
        )

    if not data:
        data = PodcastSubscriberData()
        data.podcast = podcast_id

    return data



def _wrap_podcast_group(res):
    if res['doc']['doc_type'] == 'Podcast':
        return Podcast.wrap(res['doc'])
    else:
        pg = PodcastGroup.wrap(res['doc'])
        id = res['key']
        return pg.get_podcast_by_id(id)


def search_wrapper(result):
    doc = result['doc']
    if doc['doc_type'] == 'Podcast':
        p = Podcast.wrap(doc)
    elif doc['doc_type'] == 'PodcastGroup':
        p = PodcastGroup.wrap(doc)
    p._id = result['id']
    return p


@cache_result(timeout=60*60)
def search(q, offset=0, num_results=20):

    if not q:
        return [], 0

    db = get_main_database()

    FIELDS = ['title', 'description']
    q = lucene_query(FIELDS, q)

    try:
        res = db.search('podcasts/search',
                wrapper      = search_wrapper,
                include_docs = True,
                limit        = num_results,
                stale        = 'update_after',
                skip         = offset,
                q            = q,
            )

        podcasts = list(res)

        for podcast in podcasts:
            if podcast.needs_update:
                incomplete_obj.send_robust(sender=podcast)

        return podcasts, res.total_rows

    except RequestFailed:
        return [], 0


def update_additional_data(podcast, twitter):
    podcast.twitter = twitter
    podcast.save()

    # clear the whole cache until we have a better invalidation mechanism
    cache.clear()


def update_related_podcasts(podcast, related):
    if podcast.related_podcasts == related:
        return

    podcast.related_podcasts = related
    podcast.save()


def delete_podcast(podcast):
    podcast.delete()
