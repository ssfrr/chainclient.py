'''This is a simple library for managing HAL documents'''

import requests
import logging
import json

logger = logging.getLogger(__name__)


class ConnectionError(Exception):
    pass


class ChainException(Exception):
    pass


def _request_with_error(req_type, href, data=None, auth=None):
    '''perform an HTTP GET and handle possible error codes. auth should be a
    tuple e.g. ('username', 'password'). It could also be any other Auth object
    that the requests library understands'''
    logger.debug('HTTP %s %s' % (req_type, href))
    try:
        if req_type == 'GET':
            response = requests.get(href, auth=auth)
        elif req_type == 'POST':
            response = requests.post(href, data=data, auth=auth)
        else:
            raise ChainException(
                'Unrecognized request type, use "GET" or "POST"')
    except requests.exceptions.ConnectionError as e:
        raise ConnectionError(e)

    if response.status_code == 401:
        raise ChainException(
            'Unauthorized, please authenticate the request with ' +
            'auth=("user", "pass")')
    elif response.status_code >= 400:
        raise ChainException(response.content)
    return response


def get(href, cache=True, auth=None):
    '''Performs an HTTP GET request at the given href (url) and creates
    a HALDoc from the response. The response is assumed to come back in
    hal+json format'''
    response = _request_with_error('GET', href, auth=auth).json()
    logger.debug('Received %s' % response)
    return HALDoc(response, cache=cache, auth=auth)


class AttrDict(dict):
    '''An AttrDict is just a dictionary that allows access using object
    attributes. For instance d['attr1'] is made available as d.attr1'''

    def __init__(self, *args):
        dict.__init__(self, *args)
        for k, v in self.iteritems():
            setattr(self, k, self._convert(v))

    def __setitem__(self, k, v):
        v = self._convert(v)
        dict.__setitem__(self, k, v)
        setattr(self, k, v)

    @classmethod
    def _convert(cls, v):
        if isinstance(v, AttrDict):
            return v
        if isinstance(v, dict):
            return AttrDict(v)
        elif isinstance(v, list):
            return [cls._convert(item) for item in v]
        else:
            return v


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
    returned. If the list is paginated, the user should provide the link href,
    and the RelList will take care of requesting the next page as needed.

    Note that random access with obj[i] only works for items we've already
    requested. To take advantage of the pagination handling use iteration'''

    def __init__(self, rels, next_link_href=None, cache=True, auth=None):
        self._rels = rels
        self._next_link = next_link_href
        self._should_cache = cache
        self._auth = auth

    def __len__(self):
        return len(self._rels)

    def __getitem__(self, idx):
        item = self._rels[idx]
        if isinstance(item, HALDoc):
            return item
        # it's not a full item, assume it's a link and fetch it
        resource = get(item.href, cache=self._should_cache, auth=self._auth)
        if self._should_cache:
            # cache the full resource in place of the link
            self._rels[idx] = resource
        return resource

    def append(self, item):
        self._rels.append(item)

    def extend(self, items):
        self._rels.extend(items)

    def __iter__(self):
        return RelListIter(self)

    def get_next_page(self):
        '''Goes and gets the next page of results and appends it to the list'''
        next_page = get(self._next_link, cache=self._should_cache,
                        auth=self._auth)
        if 'next' in next_page.links:
            self._next_link = next_page.links['next'].href
        else:
            self._next_link = None
        self._rels.extend(next_page.links['items'])

    def has_next_page(self):
        return self._next_link is not None


class RelListIter(object):
    '''Used to iterate through a RelList'''

    def __init__(self, link_list):
        self._link_list = link_list
        self._idx = 0

    def next(self):
        if self._idx == len(self._link_list):
            if self._link_list.has_next_page():
                logger.debug('End of page reached, requesting next page')
                self._link_list.get_next_page()
            else:
                raise StopIteration()
        item = self._link_list[self._idx]
        self._idx += 1
        return item


class RelResolver(object):
    '''A RelResolver is attached to a resource and handles retreiving related
    resources when necessary, and caching them as embedded resources'''

    def __init__(self, resource, cache=True, auth=None):
        self._resource = resource
        self._should_cache = cache
        self._auth = auth

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
                if key == 'items' and 'next' in self._resource.links:
                    # this rel is a paginated list
                    next_link = self._resource.links['next'].href
                else:
                    next_link = None
                links = RelList(self._resource.links[key], next_link,
                                cache=self._should_cache, auth=self._auth)
                if self._should_cache:
                    self._resource.embed_resource(key, links)
                return links
            # it's just one resource, so we can fetch it right here and return
            # the actual resource. We also cache it as an embedded resource so
            # next time we don't need to re-fetch it
            resource = get(rel.href, cache=self._should_cache, auth=self._auth)
            if self._should_cache:
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

    def __init__(self, response, cache=True, auth=None, *args, **kwargs):
        '''builds a HALDoc from a python dictionary. A HALDoc can also be
        treated as a standard dict to access the raw data'''
        AttrDict.__init__(self, response, *args, **kwargs)
        self.links = AttrDict()
        self.embedded = AttrDict()
        self.rels = RelResolver(self, cache=cache, auth=auth)
        self._should_cache = cache
        self._auth = auth

        if '_links' in self:
            for rel, link in self['_links'].iteritems():
                if isinstance(link, list):
                    self.links[rel] = []
                    for link_item in link:
                        self.links[rel].append(HALLink(link_item))
                else:
                    self.links[rel] = HALLink(link)

    def create(self, resource, cache=True, auth=None):
        '''Assumes this resource is some kind of collection that can have new
        resources added to it. Attempts to post the given resource to this
        resource's 'createForm' link. You can override the HALDoc's cache
        setting when creating resources, such as in a data posting script'''
        create_url = self.links.createForm.href
        # if auth info is given here, override self._auth
        auth = auth or self._auth
        logger.debug("posting %s to %s" % (resource, create_url))
        response = _request_with_error('POST', create_url,
                                       data=json.dumps(resource),
                                       auth=auth).json()

        if isinstance(response, list):
            resources = [HALDoc(item) for item in response]
            if self._should_cache and cache and 'items' in self.rels:
                # if this is a collection with an items rel then we can add the
                # new items to it
                self.rels['items'].extend(resources)
            return resources
        else:
            resource = HALDoc(response)
            if self._should_cache and cache and 'items' in self.rels:
                # if this is a collection with an items rel then we can add the
                # new item to it
                self.rels['items'].append(resource)
            return resource

    def embed_resource(self, rel, resource):
        self.embedded[rel] = resource
