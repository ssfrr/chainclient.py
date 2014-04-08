'''This is a simple library for managing HAL documents'''

import requests
import logging
import json

logger = logging.getLogger(__name__)


class ConnectionError(Exception):
    pass


def get(href):
    '''Performs an HTTP GET request at the given href (url) and creates
    a HALDoc from the response. The response is assumed to come back in
    hal+json format'''
    logger.debug('HTTP GET %s' % href)
    try:
        response = requests.get(href).json()
    except requests.exceptions.ConnectionError as e:
        raise ConnectionError(e)

    logger.debug('Received %s' % response)
    return HALDoc(response)


class AttrDict(dict):
    '''An AttrDict is just a dictionary that allows access using object
    attributes. For instance d['attr1'] is made available as d.attr1'''

    def __init__(self, *args):
        dict.__init__(self, *args)
        for k, v in self.iteritems():
            setattr(self, k, v)

    def __setitem__(self, k, v):
        dict.__setitem__(self, k, v)
        setattr(self, k, v)


class HALLink(AttrDict):
    '''Just a normal AttrDict, but one that enforces an 'href' field, so errors
    get thrown at creation time rather then later when access is attempted'''

    def __init__(self, *args):
        AttrDict.__init__(self, *args)
        if 'href' not in self:
            raise ValueError(
                "Missing required href field in link: %s" % self)


class RelList(object):
    '''A RelList represents a list of rels that will auto-retreive the data on
    demand. Typically it's initialized with a list of links that are resolved
    as needed. It may also contain full resources, in which case they are just
    returned. Note that it's not currently handling pagination'''

    def __init__(self, rels):
        self._rels = rels

    def __len__(self):
        return len(self._rels)

    def __getitem__(self, idx):
        item = self._rels[idx]
        if isinstance(item, HALDoc):
            return item
        # it's not a full item, assume it's a link and fetch it
        resource = get(item.href)
        self._rels[idx] = resource
        return resource

    def append(self, item):
        self._rels.append(item)

    def __iter__(self):
        return RelListIter(self)


class RelListIter(object):
    '''Used to iterate through a RelList'''

    def __init__(self, link_list):
        self._link_list = link_list
        self._idx = 0

    def next(self):
        if self._idx == len(self._link_list):
            raise StopIteration()
        item = self._link_list[self._idx]
        self._idx += 1
        return item


class RelResolver(object):
    '''A RelResolver is attached to a resource and handles retreiving related
    resources when necessary, and caching them as embedded resources'''

    def __init__(self, resource):
        self._resource = resource

    def __contains__(self, key):
        return key in self._resource.embedded or key in self._resource.links

    def __getitem__(self, key):
        try:
            return self._resource.embedded[key]
        except KeyError:
            # we don't have the related resource in our embedded list, go get
            # it
            logger.debug('\'%s\' not embedded, checking links...' % key)
            rel = self._resource.links[key]
            if isinstance(rel, list):
                # this is a list of related resources, so we defer to RelList
                # to handle fetching them on demand
                links = RelList(self._resource.links[key])
                self._resource.embed_resource(key, links)
                return links
            # it's just one resource, so we can fetch it right here and return
            # the actual resource. We also cache it as an embedded resource so
            # next time we don't need to re-fetch it
            resource = get(rel.href)
            self._resource.embed_resource(key, resource)
            return resource


class HALDoc(AttrDict):
    '''A HAL resource. Resource attributes can be accessed like normal python
    attributes with dot notation. If the attribute name is not a valid
    identifier they are also available with dictionary lookup syntax. Related
    resources will be retreived on demand if necessary, or if the server
    already provided them as embedded resources it will skip the extra HTTP
    GET. Most of the time HALDocs aren't created directly, but with the 'get'
    function defined in this module'''

    def __init__(self, *args):
        '''builds a HALDoc from a python dictionary. A HALDoc can also be
        treated as a standard dict to access the raw data'''
        AttrDict.__init__(self, *args)
        self.links = AttrDict()
        self.embedded = AttrDict()
        self.rels = RelResolver(self)

        if '_links' in self:
            for rel, link in self['_links'].iteritems():
                if isinstance(link, list):
                    self.links[rel] = []
                    for link_item in link:
                        self.links[rel].append(HALLink(link_item))
                else:
                    self.links[rel] = HALLink(link)

    def create(self, resource):
        '''Assumes this resource is some kind of collection that can have new
        resources added to it. Attempts to post the given resource to this
        resource's 'createForm' link'''
        create_url = self.links.createForm.href
        logger.debug("posting %s to %s" % (resource, create_url))
        try:
            response = requests.post(create_url, data=json.dumps(resource))
        except requests.exceptions.ConnectionError as e:
            raise ConnectionError(e)
        resource = HALDoc(response.json())
        if 'items' in self.rels:
            # if this is a collection with an items rel then we can add the new
            # item to it
            self.rels['items'].append(resource)
        return resource

    def embed_resource(self, rel, resource):
        self.embedded[rel] = resource
