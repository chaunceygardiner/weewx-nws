#!/usr/bin/python3

import json
import matplotlib.path as mpltPath
import optparse
import re
import requests
import sys
import time

from typing import Tuple

class CheckGrid:
    @staticmethod
    def request_twelve_hour_url(latitude: float, longitude: float) -> str:
        url = 'https://api.weather.gov/points/%f,%f' % (latitude, longitude)
        session= requests.Session()
        headers = {'User-Agent': '(weewx-nws test run, weewx-nws-developer)'}
        response: requests.Response = session.get(url=url, headers=headers, timeout=5)
        response.raise_for_status()
        j: Dict[str, Any] = response.json()
        return j['properties']['forecast']

    @staticmethod
    def parse_url(url: str) -> Tuple[str, int, int]:
        # https://api.weather.gov/gridpoints/MTR/92,88/forecast
        chop = re.sub('https://api.weather.gov/gridpoints/', '', url)
        chop = re.sub('/forecast', '', chop)
        segments = chop.split('/')
        office = segments[0]
        grid = segments[1].split(',')
        x = int(grid[0])
        y = int(grid[1])
        return office, x, y

    @staticmethod
    def request_forecast_polygon(office, x, y):
        url = 'https://api.weather.gov/gridpoints/' + office + '/' + str(x) + ',' + str(y) + '/forecast'
        session= requests.Session()
        headers = {'User-Agent': '(weewx-nws test run, weewx-nws-developer)'}
        headers['Feature-Flags'] =  '%f' % time.time()
        response: requests.Response = session.get(url=url, headers=headers, timeout=5)
        if response.status_code == 500:
            time.sleep(2)
            response = session.get(url=url, headers=headers, timeout=5)
            if response.status_code == 500:
                time.sleep(2)
                response = session.get(url=url, headers=headers, timeout=5)
        response.raise_for_status()
        j = response.json()
        resp_polygon = j['geometry']['coordinates'][0]
        # The polygon in the response has lat and long reversed!  Reverse them.
        polygon = []
        for point in resp_polygon:
            polygon.append([ point[1], point[0] ])
        return polygon

    @staticmethod
    def check_forecast_contains_lat_long(office, x, y, lat, long) -> bool:
        polygon = CheckGrid.request_forecast_polygon(office, x, y)
        path = mpltPath.Path(polygon)
        return path.contains_point([lat, long])

    @staticmethod
    def try_grid(office, x, y, lat, long) -> bool:
        try:
            inside = CheckGrid.check_forecast_contains_lat_long(office, x, y, lat, long)
        except:
            inside = False
        if inside:
            print('Add the following two lines to the [NWS] section in weewx.conf:')
            print('    twelve_hour_forecast_url = "https://api.weather.gov/gridpoints/%s/%d,%d/forecast"' % (office, x, y))
            print('    one_hour_forecast_url = "https://api.weather.gov/gridpoints/%s/%d,%d/forecast/hourly"' % (office, x, y))
            print()
        return inside

if __name__ == '__main__':
    usage = """%prog --latitude <latitude> --longitude <longitude> [--help]"""

    def main():
        parser = optparse.OptionParser(usage=usage)
        parser.add_option('--latitude', type='float', dest='lat',
                          help='The latitude of the station.')
        parser.add_option('--longitude', type='float', dest='long',
                          help='The longitude of the station.')
        (options, args) = parser.parse_args()

        if not options.lat or not options.long:
            parser.error('--latitude and --longitude are required arguments')
        options.lat, options.long

        lat = options.lat
        long = options.long
        url = CheckGrid.request_twelve_hour_url(lat, long)
        office, x, y = CheckGrid.parse_url(url)

        inside = CheckGrid.check_forecast_contains_lat_long(office, x, y, lat, long)

        if inside:
            print('nws computed the correct grid(%d, %d) for lat/long %f/%f' % (x, y, lat, long))
        else:
            print('nws computed the incorrect grid(%d, %d) for lat/long %f/%f' % (x, y, lat, long))
            print()

            # Define a list of grids to try.
            grids = [
                [ x + 1, y + 1],
                [ x + 1, y    ],
                [ x    , y + 1],
                [ x    , y - 1],
                [ x - 1, y    ],
                [ x - 1, y - 1]]

            for grid in grids:
                inside = CheckGrid.try_grid(office, grid[0], grid[1], lat, long)
                if inside:
                    sys.exit(0)

            print('Could not find correct grid to use.  Try running again.')

            #inside = CheckGrid.try_grid(office, x + 1, y + 1, lat, long)
            #if not inside:
            #    inside = CheckGrid.try_grid(office, x - 1, y - 1, lat, long)
            #    if not inside:
            #        print('Could not find correct grid to use.  Try running again.')

    main()
