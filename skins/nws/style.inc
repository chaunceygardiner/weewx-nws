## Copyright 2024 John A Kline
## See LICENSE.txt for your rights
#errorCatcher Echo
#encoding UTF-8
    <style>
      /* The drawn icons carry no width/height of their own -- sizing is the
         skin's job.  86px is what NWS's `?size=medium` raster measured, so the
         pages lay out exactly as they did when they hot-linked it. */
      .wxi {
        width: 86px;
        height: 86px;
        vertical-align: middle;
      }
      /* NWS added a condition we have no symbol for: its own image, kept in
         the same box a drawn icon would have filled. */
      img.wxi-fallback {
        object-fit: contain;
      }
      /* NWS itself had no icon for the period.  Empty, so say so faintly
         rather than leaving what looks like a layout hole. */
      .wxi-unknown {
        border: 1px dashed LightGray;
        border-radius: 4px;
        box-sizing: border-box;
      }
      .forecastnav {
        overflow: hidden;
      }
      .forecastnav a {
        float: left;
        color: #f2f2f2;
        text-align: center;
        padding: 14px 0px;
        text-decoration: none;
        font-size: 17px;
      }
      .forecastnav a:hover {
        background-color: #ddd;
        color: black;
      }
      .forecastnav a.active {
        background-color: #367ba3;
        color: white;
      }
    </style>
