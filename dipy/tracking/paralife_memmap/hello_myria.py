#!/usr/bin/python

from myria import *

name = {'userName': 'public', 'programName': 'adhoc', 'relationName': 'Books'}
schema = { "columnNames" : ["name", "pages"],
           "columnTypes" : ["STRING_TYPE","LONG_TYPE"] }
data = """Brave New World,288
Nineteen Eighty-Four,376
We,256"""

connection = MyriaConnection(rest_url='http://demo.myria.cs.washington.edu:8753')
result = connection.upload_file(
    name, schema, data, delimiter=',', overwrite=True)

relation = MyriaRelation("Books", connection=connection)
print relation.to_dict()
print "Done"
