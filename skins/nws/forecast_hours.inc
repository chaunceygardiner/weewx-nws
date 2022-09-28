## forecast hours - Copyright 2020 John A Kline
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
            <img src='$icon' alt='$icon'>
          </td>
        #end for
      </tr>
      <tr>
        #for $hour in $nwsforecast.one_hour_forecasts(7)
          <td style='width:14.2857%;vertical-align:top;$at_a_glance_padding'>
            $hour.outTemp.format('%.0f') $hour.outTempTrend<br>
            $hour.shortForecast
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
        <td style='width:20%;'><img src='$icon' alt='$icon'></td>
        <td style='width:80%;'>
          <table style='width:100%;border-bottom:none;padding:0px;'>
            <tr><td style='font-size:$title_font_size;font-weight:bold;border-bottom:1pt solid LightGray;'>$hour.startTime.format('%a %l %p')</td></tr>
            <tr class='forecast_hours_inner_row'>
              <td style='border-bottom:none;'>
                <table style='width:100%;border-bottom:none;padding:0px;'>
                  <tr>
                    <td style='width:34%;'>$hour.shortForecast</td>
                    <td style='width:33%;'>$hour.outTemp.format('%.0f')</td>
                    <td style='width:33%;'>$hour.windSpeed.format('%.0f') $hour.windDir.ordinal_compass</td>
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
