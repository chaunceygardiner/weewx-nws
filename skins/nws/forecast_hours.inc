## forecast hours - Copyright 2020-2024 John A Kline
## See LICENSE.txt for your rights
#errorCatcher Echo
#encoding UTF-8
<div id='forecast_hours'>
  #set $at_a_glance_padding = 'padding:15px;'
  <div>
    <table style='width:97%;text-align:center;$at_a_glance_padding'>
      <tr>
        #for $hour in $nwsforecast.one_hour_forecasts(7)
          <td style='width:14.2857%;vertical-align:bottom;$at_a_glance_padding'>
            <span style='border-bottom:1pt solid LightGray;'>$hour.startTime.format('%l %p')</span>
          </td>
        #end for
      </tr>
      <tr>
        #for $hour in $nwsforecast.one_hour_forecasts(7)
          <td style='width:14.2857%;$at_a_glance_padding'>
            #set $icon = $hour.iconUrl
            #set icon = $icon.replace('?size=small', '?size=medium')
            #set icon = $icon.replace(',0?', '?')
            <img src='$icon' alt='$icon'>
          </td>
        #end for
      </tr>
      <tr>
        #for $hour in $nwsforecast.one_hour_forecasts(7)
          <td style='width:14.2857%;vertical-align:top;$at_a_glance_padding'>
            $hour.outTemp.format('%.0f')$unit.label.outTemp $hour.outTempTrend<br>
            $hour.shortForecast<br>
            PoP: $hour.pop.format('%.0f')$unit.label.pop
          </td>
        #end for
      </tr>
    </table>
  </div>
  <br>
  <div style='width:100%;'>
    <table style='width:97%;text-align:center;border-style:solid;padding:30px;border:1pt solid LightGray;'>
      ## --------------------------------------------------
      ## |       |                Sat 8 PM                |
      ## | ICON  |----------------------------------------|
      ## |       |  Mostly Clear   66°F       7 mph WNW   |
      ## --------------------------------------------------
      #set title_font_size = 'large'
      #set $forecast_generated_at = ''
      #for $hour in $nwsforecast.one_hour_forecasts()
      #set $forecast_generated_at = $hour.generatedTime
      <tr class='forecast_hours'>
        #set icon = $hour.iconUrl
        #set icon = $icon.replace('?size=small', '?size=medium')
        #set icon = $icon.replace(',0?', '?')
        <td style='width:20%;'><img src='$icon' alt='$icon'></td>
        <td style='width:80%;'>
          <table style='width:100%;border-bottom:none;padding:0px;'>
            <tr><td style='font-size:$title_font_size;font-weight:bold;border-bottom:1pt solid LightGray;'>$hour.startTime.format('%a %l %p')</td></tr>
            <tr class='forecast_hours_inner_row'>
              <td style='border-bottom:none;'>
                <table style='width:100%;border-bottom:none;padding:0px;'>
                  <tr>
                    <td style='width:34%;'>Forecast<br>$hour.shortForecast</td>
                    <td style='width:33%;'>Temperature<br>$hour.outTemp.format('%.0f')$unit.label.outTemp<br>
                    </td>
#if $hour.windSpeed2 is None
                    <td style='width:33%;'>Wind<br>$hour.windSpeed.format('%.0f')$unit.label.windSpeed $hour.windDir.ordinal_compass</td>
#else
                    <td style='width:33%;'>Wind<br>$hour.windSpeed.format('%.0f') to hour.windSpeed2.format('%.0f')$unit.label.windSpeed $hour.windDir.ordinal_compass</td>
#end if
                  </tr>
                  <tr>
                    <td style='width:34%;'>Prob. of Precip.<br>$hour.pop.format('%.0f')$unit.label.pop</td>
                    <td style='width:33%;'>Dewpoint<br>$hour.dewpoint.format('%.0f')$unit.label.dewpoint</td>
                    <td style='width:33%;'>Rel. Humidity<br>$hour.outHumidity.format('%.0f')$unit.label.outHumidity</td>
                  </tr>
                </table>
              </td>
            </tr>
          </table>
        </td>
      </tr>
      #end for
    </table>
    #if $forecast_generated_at != ''
    <div style='text-align:center;font-style:italic;color:Gray;'>Forecast generated $forecast_generated_at.</div>
    #end if
  </div>
</div>
