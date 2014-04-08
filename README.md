ChainClient
===========

ChainClient is a client module for the [Chain API][chain].

QuickStart
----------

Typically the starting place is the `get` function, which will go
fetch a resource from the given root URL.

    import chainclient

    site_url = 'http://chain-api.media.mit.edu/sites/3'
    site = chainclient.get(site_url)

`site` is an instance of HALDoc, which basically takes advantage of the
hal+json format used by the Chain API to provide some convenience functions.
For instance, resource attributes like the name of the site can be accessed
with `site.name`.

Another feature of chainclient is that it will automatically go fetch related
resources, but is smart enough to know not to fetch them if they were already
provided by the server, or if they've been fetched previously. In general you
should access related resources through the "rels" attribute, e.g.

    devices_coll = site.rels['ch:devices']

which will go fetch the collection of devices in a site. The devices collection
has a rel called 'items' that is the actual list of devices, you can iterate through
the list as normal:

    for dev in devices_coll.rels['items']:
        print(dev.name)

Note that as you iterate through the collection it will automatically fetch new
devices as needed. If you have the logging module set to DEBUG you can see logs
of whenever the library fetches over HTTP.

You can create new resources as well, by adding them to any resource with a
'createForm' link, such as our friendly device collection here.

    new_device_data = {'name': 'My Cool Device'}
    resource = devices_coll.create(new_device_data)

Which will POST a new device to the collection and return the newly created
HALDoc.

For specifics on the different resource types see the
[Chain API documentation][chain-doc]

[chain]: https://github.com/ssfrr/chain-api
[chain-doc]: https://github.com/ssfrr/chain-api#general-api-concept-overview
