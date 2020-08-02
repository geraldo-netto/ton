#!/usr/bin/env python
# -*- coding: utf-8 -*-

import datetime
import json
import os.path
import random
import re
import sys

def readJsonFile(filePath):
	with open(filePath) as jsonFile:
		return json.load(jsonFile)

def extractVariables(format):
	return re.findall(r"\$(.*?)\$", format)

def padValue(value, jsonNode):
	return str(value).zfill(len(str(jsonNode['maxValue'])))

def createBooleanValue(jsonNode):
	return random.choice([jsonNode['whenTrue'], jsonNode['whenFalse']])

def createIntegerValue(jsonNode):
	value = random.randint(jsonNode['minValue'], jsonNode['maxValue'])

	if jsonNode['padWithZero']:
		value = padValue(value, jsonNode)

	return value

def createDecimalValue(jsonNode):
	value = round(random.uniform(jsonNode['minValue'], jsonNode['maxValue']), jsonNode['decimals'])

	if jsonNode['padWithZero']:
		value = padValue(value, jsonNode)

	return value

def createCharValue(jsonNode):
	value = u''
	for char in range(0, jsonNode['maxChar']):
		value = value + random.choice(jsonNode['values'])

	return value

def createStringValue(jsonNode):
	return random.choice(jsonNode['values'])



if len(sys.argv) < 2:
	print("TON (c) 2020 Geraldo Netto\nUsage: %s <config.json>" % str(sys.argv[0]))
	sys.exit(0)

if os.path.isfile(sys.argv[1]):
	config = readJsonFile(sys.argv[1])
	rowsLength = config['rows']
	format = config['format']
	variables = extractVariables(format)
	iniDate = datetime.datetime.now()

	for row in range(1, rowsLength):
		currRow = format

		for variable in variables:
			if config['types'][variable]['type'] == 'boolean':
				currRow = currRow.replace('$' + variable + '$', createBooleanValue(config['types'][variable]))

			elif config['types'][variable]['type'] == 'integer':
				currRow = currRow.replace('$' + variable + '$', createIntegerValue(config['types'][variable]))

			elif config['types'][variable]['type'] == 'decimal':
				currRow = currRow.replace('$' + variable + '$', createDecimalValue(config['types'][variable]))

			elif config['types'][variable]['type'] == 'char':
				currRow = currRow.replace('$' + variable + '$', createCharValue(config['types'][variable]))

			elif config['types'][variable]['type'] == 'string':
				currRow = currRow.replace('$' + variable + '$', createStringValue(config['types'][variable]))

		print currRow

	print "elapsed time: ", datetime.datetime.now() - iniDate

else:
	print("unable to parse %s" % str(sys.argv[1]))
	sys.exit(1)
