# TON
TON is a mass data generator script written in python

## Usage
```bash
netto@bella:~/ton$ python ton.py hwmetrics.json
1881-09-27 14:52:36;hg;ARM;N;AC;38.98
1373-08-13 23:43:56;hg;AMD;N;AB;30.18
1100-12-19 18:54:41;hg;AMD;Y;AC;68.69
1479-07-24 12:20:20;hg;ARM;Y;AB;93.21
1775-01-07 13:30:12;hg;ARM;Y;CA;63.47
1510-11-05 01:43:15;hg;Intel;N;AB;37.75
1630-03-17 16:38:15;hg;Intel;Y;BA;87.15
1830-12-11 14:47:50;hg;ARM;Y;CB;86.69
1844-11-28 10:46:00;hg;Intel;N;BA;23.21
elapsed time:  0:00:00.000648
```

### Explaining [hwmetrics.json](examples/hwmetrics.json)

[hwmetrics.json](examples/hwmetrics.json) declares how data must be created and it has the following format:
```json
{
  "encoding": "UTF-8",
  "rows": 10,
  "format": "$integer_variable$;$string_variable$;$char_variable$;$boolean_variable$;$decimal_variable$",
  "types": {
    "integer_variable": {
      "type": "integer",
      "minValue": 1100,
      "maxValue": 2050,
      "padWithZero": true
    },
    "string_variable": {
      "type": "string",
      "values": ["AMD", "INTEL", "ARM"]
    },
    "char_variable": {
      "type": "char",
      "values": ["A", "B", "C"],
      "maxChar": 2
    },
    "boolean_variable": {
      "type": "boolean",
      "whenTrue": "Y",
      "whenFalse": "N"
    },
    "decimal_variable": {
      "type": "decimal",
      "minValue": 0.0,
      "maxValue": 100.0,
      "decimals": 2,
      "padWithZero": true
    }
  }
}

```

"rows" is the number of rows TON will create, it must be an integer

"format" is the output string that each row will have. All values enclosed by '$' is read as a variable.
e.g.: $title$ will create a variable title that must be mapped inside the types block.

"types" contains a list of variables previously declared on format

The following data types are allowed inside types:
#### boolean creates boolean value
```json
"variableName": {
  "type": "boolean",
  "whenTrue": "Y",
  "whenFalse": "N"
}
```

#### char creates single character value
"maxChar": 2 => maximum number of characters to be created
```json
"variableName": {
  "type": "char",
  "values": ["A", "B", "C"],
  "maxChar": 2
}
```

#### string creates string values
```json
"variableName": {
  "type": "string",
  "values": ["AMD", "INTEL", "ARM"]
}
```

#### integer creates integer values
"minValue": 1100 => defines the minimum value to be created
"maxValue": 2050 => defines the maximum value to be created
"padWithZero": true => completes the created integer with zeros
```json
"variableName": {
  "type": "integer",
  "minValue": 1100,
  "maxValue": 2050,
  "padWithZero": true
}
```

#### decimal creates decimal values
"minValue": 0.0 => defines the minimum value to be created
"maxValue": 100.0 => defines the maximum value to be created
"decimals": 2 => defines the maximum value to be created
"padWithZero": true => completes the created float with zeros
```json
"variableName": {
  "type": "decimal",
  "minValue": 0.0,
  "maxValue": 100.0,
  "decimals": 2,
  "padWithZero": true
}
```

#### lmhash creates windows 2000/xp hashes based on their literal values
Also, lmhash has a special parameter called id that is used to extract field name.
e.g.: Variable $word$ applied with lmhash will create an md4 hash;
      Variable $word[id]$ applied with lmhash will display the current value
So: "$word[id]$ => $word$" will generate this kind of output: "love => 85deeec2d12f917783b689ae94990716"
Please, check full [winhash.json example](examples/winhash.json)
```json
"variableName": {
  "type": "lmhash",
  "values": ["AMD", "Intel", "ARM"]
}
```

Please, check the following example for other use cases:
* [dna.json example - creating DNA sequences in the same format as 23andMe, tellmeGen, ...](examples/dna.json)
* [winhash.json example - creating rainbow table of Windows 2000/XP](examples/winhash.json)


## TODO
* refactoring
* tests
* add sequential number generation
* allow to change statistical data distribution (currently, it's all based on a normal curve)

## License
[BSD-3](https://opensource.org/licenses/BSD-3-Clause)
