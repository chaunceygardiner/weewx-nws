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

1.  To get daily forecasts (in this example, all 7 days (2 per day) forecasts will be returned.
   ```
    #for $day in $nwsforecast.daily_forecasts(14)
        $day.generatedTime
        $day.number
        $day.name
        $day.startTime
        $day.endTime
        $day.isDaytime
        $day.outTemp
        $day.outTempTrend
        $day.windSpeed
        $day.windDir
        $day.iconUrl
        $day.shortForecast
        $day.detailedForecast
    #end for
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
    #end for
    ```

1.  To get alerts:
    ```
    #for $alert in $nwsforecast.alerts()
        $alert.effective   # Time issued
        $alert.onset       # Time it will begin
        $alert.ends        # Time it will end
        $alert.event       # Name of event (e.g., Heat Advisory)
        $alert.headline    # Headline
        $alert.description # Long description
    #end for
   ```

## Licensing

weewx-purple is licensed under the GNU Public License v3.
