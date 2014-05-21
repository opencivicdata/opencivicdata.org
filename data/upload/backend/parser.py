import re
import csv
from data.upload.backend.xlrd import xlrd_dict_reader
from data.upload.backend.csv import csv_dict_reader
from data.upload.models import (SpreadsheetUpload, SpreadsheetPerson,
                                SpreadsheetUploadSource, SpreadsheetPersonSource,
                                SpreadsheetLink, SpreadsheetContactDetail)

from contextlib import contextmanager
from pupa.scrape.helpers import Legislator, Person
from pupa.scrape.popolo import Organization


def people_to_pupa(stream, transaction):
    org = Organization(
        name=transaction.jurisdiction.name,
        classification='legislature',
    )

    for person in stream:
        name = person.name
        position = person.position
        district = person.district
        image = person.image

        if not name:
            raise ValueError("A name is required for each entry.")

        if position is None:
            position = "member"

        if not district:
            obj = Person(name=name)
            # OK. Let's manually create the relation without the district.
            # (If they don't have a district, it's assumed they're a member
            #  of the org, but not a "legislator". Something like Mayor, where
            #  they hold membership, but not a district).
            obj.add_membership(
                organization=org,
                label=person.position,
                role=person.position,
            )
            org.add_post(label=position, role=position)
        else:
            obj = Legislator(name=name, district=district)
            org.add_post(label=district, role=position)
            if person.party:
                obj._party = person.party

        if image:
            obj.image = image

        for detail in person.contacts.all():
            obj.add_contact_detail(
                type=detail.type,
                value=detail.value,
                note=detail.note,
            )

        for link in person.links.all():
            obj.add_link(
                url=link.url,
                note=link.url
            )

        for source in (list(person.sources.all())
                       + list(transaction.sources.all())):
            obj.add_source(
                url=source.url,
                note=source.note,
            )

        obj.validate()
        obj.pre_save(transaction.jurisdiction.id)

        yield obj

        for related in obj._related:
            yield related

    for related in org._related:
        yield related
    yield org


def import_parsed_stream(stream, user, jurisdiction, sources):
    upload = SpreadsheetUpload(user=user, jurisdiction=jurisdiction)
    upload.save()

    for source in sources:
        a = SpreadsheetUploadSource(
            upload=upload,
            url=source,
            note="Default Spreadsheet Source"
        )
        a.save()


    for person in stream:
        if not person['Name']:
            raise ValueError("Bad district or name")

        position = person.pop("Position")
        district = person.pop("District")

        if not position:
            position = "member"

        who = SpreadsheetPerson(
            name=person.pop('Name'),
            spreadsheet=upload,
            position=position,
            district=district,
        )

        if 'Image' in person:
            who.image = person.pop("Image")

        if 'Party' in person:
            who.party = person.pop("Party")

        who.save()

        contact_details = {
            "Address": "address",
            "Phone": "voice",
            "Email": "email",
            "Fax": "fax",
            "Cell": "voice",
            "Twitter": "twitter",
            "Facebook": "facebook"
        }
        links = ["Website", "Homepage"]
        sources = ["Source"]

        for key, value in person.items():
            if not value:
                # 'errything is optional.
                continue

            match = re.match("(?P<key>.*) (?P<label>\(.*\))?", key)
            root = key
            label = None
            if match:
                d = match.groupdict()
                root = d['key']
                label = d['label'].rstrip(")").lstrip("(")

            if root in sources:
                a = SpreadsheetPersonSource(
                    person=who,
                    url=value,
                    note=key
                )
                a.save()
                continue

            # If we've got a link.
            if root in links:
                a = SpreadsheetLink(
                    person=who,
                    url=value,
                    note=key,
                )
                a.save()
                continue

            # If we've got a contact detail.
            if root in contact_details:
                type_ = contact_details[root]
                a = SpreadsheetContactDetail(
                    person=who,
                    type=type_,
                    value=value,
                    label=label or "",
                    note=key,
                )
                a.save()
                continue

            raise ValueError("Unknown spreadhseet key: %s" % (key))

    return upload


def import_stream(stream, extension, user, jurisdiction, sources):
    reader = {"csv": csv_dict_reader,
              "xlsx": xlrd_dict_reader,
              "xls": xlrd_dict_reader}[extension]

    return import_parsed_stream(reader(stream), user, jurisdiction, sources)


@contextmanager
def import_file_stream(fpath, user, jurisdiction, sources):
    _, xtn = fpath.rsplit(".", 1)

    with open(fpath, 'br') as fd:
        yield import_stream(fd, xtn, user, jurisdiction, sources)
