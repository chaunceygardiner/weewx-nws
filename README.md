# weewx-nws
*Open source plugin for WeeWX software.

## Description

A WeeWX extension for NWS forecasts.

Copyright (C)2020 by John A Kline (john@johnkline.com)

**THIS PLUGIN REQUIRES PYTHON 3 AND WEEWX 4**

# Installation Instructions

1. Download weewx-nws-master.zip from the https://github.com/chaunceygardiner/weewx-nws page.

1. Run the following command.
   ```
   sudo /home/weewx/bin/wee_extension --install weewx-nws-master.zip
   ```
   Note: The above command assumes a WeeWX installation of `/home/weewx`.
         Adjust the command as necessary.

1. Edit weewx.conf to fill in User-Agent with your weather site and contact information.
   [NWS]
       User-Agent: '(my-weather-site.com, me@my-weather-site.com)'

1. Restart WeeWX.

# How to access NWS Forecasts in reports.

1. Add NWSForecastVariables to a  skin.  For example, to add to the Seasons skin, add:
   ```
    [StdReport]
        [[SeasonsReport]]
            [[[CheetahGenerator]]]
                search_list_extensions = user.nws.NWSForecastVariables
   ```

1.  To get hourly forecasts (in this example, the next 12 forecasts will be returned).
   ```
    #for $hour in $nwsforecast.hourly_forecasts(12)
        $hour.generatedTime
        $hour.number
        $hour.name
        $hour.startTime
        $hour.endTime
        $hour.isDaytime
        $hour.outTemp
        $hour.outTempTrend
        $hour.windSpeed
        $hour.windDir
        $hour.iconUrl
        $hour.shortForecast
        $hour.detailedForecast
   ```

## Licensing

weewx-purple is licensed under the GNU Public License v3.
