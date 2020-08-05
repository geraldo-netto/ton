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

hwmetrics.json declares how data must be generated and it has the following format:
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

## TODO
* refactoring
* tests
* add sequencial number generation
* allow to change statistical data distribution (currently, it's all based on a normal curve)

## License
[BSD-3](https://opensource.org/licenses/BSD-3-Clause)
