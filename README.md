# dnserver

Simple DNS server written in python for use in development and testing.
This project adds simple "split-brain" ability.

The DNS serves it's own records, if none are found it responds with `NXDOMAIN`.

You can setup records you want to serve with a custom `zones.txt` file, 
see [example_zones.txt](example_zones.txt) for the format.

You can also specify internal records which are only served if the value of one record in `zones.txt` matches the client's IP address. See [example_internal_zones.txt](example_internal_zones.txt) for an example.

Records can be updated via the built-in Web server.

To use with docker:

    docker build -t dnsserer .
    docker run -p 5053:53/udp -p 5053:53/tcp -p 5000:5000 --rm dnserver

Or with custom zone files

    docker run -p 5053:53/udp -p 5053:53/tcp -p 5000:5000 -v `pwd`/zones.txt:/zones/zones.txt -v `pwd`/internal_zones.txt:/zones/internal_zones.txt --rm dnserver

(assuming you have your zone records at `./zones.txt` and internal zone records at `./internal_zones.txt`, 
TCP isn't required to use `dig`, hence why it's omitted in this case.)

To run without docker (assuming you have `dnslib==0.9.7` and python 3.6 installed):

    PORT=5053 ZONE_FILE='./example_zones.txt' INTERNAL_ZONE_FILE='./example_internal_zones.txt' ./dnserver.py

## Examples

This example queries the local dnserver from a LAN interface. Client's IP is `192.168.123.123`. Retrieves the non-internal record.

```shell
~ ➤  dig @192.168.123.123 -p 5053 example.com 
...
;; ANSWER SECTION:
example.com.		300	IN	A	172.17.0.1

;; Query time: 1 msec
;; SERVER: 192.168.1.159#5053(192.168.1.159)
;; WHEN: Sat Feb 10 12:53:37 CET 2018
;; MSG SIZE  rcvd: 45
```

This example queries the dnserver from the (docker's) VLAN interface.  Client IP is `172.17.0.1`.  Retrieves the internal record because client ip and external record's value match.

```shell
~ ➤  dig @localhost -p 5053 example.com 
...
;; ANSWER SECTION:
example.com.		300	IN	A	192.168.123.123

;; Query time: 1 msec
;; SERVER: 192.168.1.159#5053(192.168.1.159)
;; WHEN: Sat Feb 10 12:53:37 CET 2018
;; MSG SIZE  rcvd: 45

```

Update records by `POST`ing to the Web server's port using this scheme: `<address:port>/<domain>/<external ip>/[internal ip]`. For example:

    curl -X POST localhost:5000/example.com/1.2.3.4/192.168.1.2

Or just update the external ip:

    curl -X POST localhost:5000/example.com/1.2.3.4

If the record does not exist, it is added.

## Environment variables

| Variable | Description | Default value |
| -------- | ----------- | ------------- |
| PORT     | DNS server port | 53 |
| WEBPORT  | Web server port | 5000 |
| TTL      | TTL for records | 300 |
| ZONE_FILE | Path to initial zone file | `/zones/zones.txt` |
| INTERNAL_ZONE_FILE | Path to initial internal zone file | `/zones/internal_zones.txt` |

