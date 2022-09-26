## Copyright John A Kline
## See LICENSE.txt for your rights
#errorCatcher Echo
#encoding UTF-8
<div>
  <table style='width:97%;text-align:center;border-style:solid;padding:30px;border:1pt solid LightGray;'>
    #set $title_font_size = 'large'
    #set $forecast_generated_at = ''
    #for $twelve_hour in $nwsforecast.twelve_hour_forecasts()
    #set $forecast_generated_at = $twelve_hour.generatedTime ##.format('%a %l %p')
    <tr>
      <td>
        ## ------------------------------------------------
        ## |       |               |                       |
        ## |       |     Temp      |     Memorial Day      |
        ## |       |     78 F      |-----------------------|
        ## | ICON  | rising slowly |  Partly cloudy with   |
        ## |       |      Wind     |  high of 84.  Winds   |
        ## |       |   1 mph NNW   |  between 1 and 9 mph  |
        ## |       |               |                       |
        ## -------------------------------------------------
        <table style='width:100%;border-bottom:1pt solid LightGray;padding:15px;'>
          <tr>
            #set $icon = $twelve_hour.iconUrl
            <td style='width:16%;'><img src='$icon' alt='$icon'/></td>
            <td style='width:30%;'>
              <table style='width:100%;text-align:center;'>
                <tr style='width:100%;'><td>Temp</td></tr>
                <tr style='width:100%;'><td>$twelve_hour.outTemp.format('%.0f') $twelve_hour.outTempTrend </td></tr>
                <tr style='width:100%;'><td>Wind</td></tr>
                <tr style='width:100%;'><td>$twelve_hour.windSpeed.format('%.0f') $twelve_hour.windDir.ordinal_compass</td></tr>
              </table>
            </td>
            <td style='width:54%;'>
              <table style='width:100%;text-align:center;'>
                <tr style='width:100%;'><td style='text-align:center;font-size:$title_font_size;font-weight:bold;border-bottom:1pt solid LightGray;'>$twelve_hour.name</td></tr>
                <tr style='width:100%;'><td>$twelve_hour.detailedForecast</td></tr>
              </table>
            </td>
          </tr>
        </table>
      </td>
    </tr>
    #end for
    #if $forecast_generated_at != ''
    <tr>
      <td style='text-align:center;font-style:italic;color:Gray;'>Forecast generated $forecast_generated_at.</td>
    </tr>
    #end if
  </table>
</div>
