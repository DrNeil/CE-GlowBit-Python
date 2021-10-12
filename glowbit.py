import os
_SYSNAME = os.uname().sysname

if _SYSNAME == 'rp2':
    from machine import Pin
    import micropython
    import rp2

if _SYSNAME == 'Linux':
    import rpi_ws281x as ws

    # Dummy ptr32() for within micropython.viper
    def ptr32(arg):
        return arg
    # Dummy class for @micropython decorator
    class micropython():
        def viper(func):
            def wrapper(*args, **kwargs):
                return func(*args, **kwargs)
            return wrapper
    
    # Dummy class for @rp2 decorator
    class rp2():
        class PIO():
            OUT_LOW = None
            SHIFT_LEFT = None
        def asm_pio(sideset_init, out_shiftdir, autopull, pull_thresh):
            def wrapper(*argx, **kwargs):
                return None
            return wrapper 


from petme128 import petme128
import time
import array
import gc

## @brief
#
# Methods for transforming colours to 32-bit packed GlowBit colour values
#
# A packed 32-bit GlowBit colour is an integer with 8-bits per colour channel data encoded in hexadecimal as follows:
# 
# 0x00RRGGBB
#
# where RR, GG, and BB are hexadecimal values (decimal [0,255]) and the most significant 8 bits are reserved and left as zero.

class colourFunctions():

    ## @brief Converts an integer "colour wheel position" to a packed 32-bit RGB GlowBit colour value.
    #
    # The "pos" argument is required as this is a micropython viper function.
    #
    # \param pos: Colour wheel position [0,255] is mapped to a pure hue in the RGB colourspace. A value of 0 or 255 is mapped to pure red with a smooth red-yellow-green-blue-purple-magenta-red transion for other values.
    # \return 32-bit integer GlowBit colour value

    @micropython.viper
    def wheel(self,pos: int) -> int:
        # Input a value 0 to 255 to get a color value.
        # The colours are a transition r - g - b - back to r.
        pos = pos % 255
        if pos < 85:
            return ((255 - pos * 3)<<16) |  ((pos * 3)<<8)
        if pos < 170:
            pos -= 85
            return ((255 - pos * 3)<<8 | (pos * 3))
        pos -= 170
        return ((pos * 3)<<16) | (255 - pos * 3)
    
    ## @brief Converts the r, g, and b integer arguments to a packed 32-bit RGB GlowBit colour value
    #
    # All arguments are required as this is a micropython viper function.
    #
    # \param r: The red intensity, [0,255]
    # \param g: The green intensity, [0,255]
    # \param b: The blue intensity, [0,255]
    # \return Packed 32-bit GlowBit colour value

    @micropython.viper
    def rgb2GBColour(self, r: int, g: int, b: int) -> int:
        return ( (r<<16) | (g<<8) | b )
   
    ## @brief Converts a 32-bit GlowBit colour value to an (R,G,B) tuple.
    #
    # \param colour A 32-bit GlowBit colour value
    # \return A tuple in the format (R,G,B) containing the RGB components of the colour parameter

    def glowbitColour2RGB(self, colour):
        return ( (colour&0xFF0000) >> 16) , (colour&0xFF00)>> 8, (colour&0xFF) )

## @brief Methods which calculate colour gradients.
#
# Custom colour map methods can be written and passed to several GlowBit library methods (eg: glowbit.stick.graph1D) but must accept the same positional arguments as the methods in this class.

class colourMaps():

    ## @brief Trivial colourmap method which always returns the colour in the parent object.
    #
    # \param index Dummy argument for compatibility with colourmap method API
    # \param minIndex Dummy argument for compatibility with colourmap method API
    # \param maxIndex Dummy argument for compatibility with colourmap method API

    def colourMapSolid(self, index, minIndex, maxIndex):
        return self.colour
        

    ## @brief Maps the pure hue colour wheel between minIndex and maxIndex
    #
    # \param index The value to be mapped
    # \param minIndex The value of index mapped to a colour wheel angle of 0 degrees
    # \param maxIndex The value of index mapped to a colour wheel angle of 360 degrees
    # \return The 32-bit packed GlowBit colour value 

    def colourMapRainbow(self, index, minIndex, maxIndex):
        return self.wheel(int(((index-minIndex)*255)/(maxIndex-minIndex)))

## @brief Low-level methods common to all GlowBit classes

class glowbit(colourFunctions):
    @rp2.asm_pio(sideset_init=rp2.PIO.OUT_LOW, out_shiftdir=rp2.PIO.SHIFT_LEFT, autopull=True, pull_thresh=24)
    def __ws2812():
        T1 = 2
        T2 = 5
        T3 = 3
        wrap_target()
        label("bitloop")
        out(x, 1)               .side(0)    [T3 - 1]
        jmp(not_x, "do_zero")   .side(1)    [T1 - 1]
        jmp("bitloop")          .side(1)    [T2 - 1]
        label("do_zero")
        nop()                   .side(0)    [T2 - 1]
        wrap()

    @micropython.viper
    def __pixelsShowPico(self):
        self.__syncWait()
        gc.collect()
        ar = self.dimmer_ar
        br = int(self.brightness)
        for i,c in enumerate(self.ar):
            r = int((((int(c) >> 16) & 0xFF) * br) >> 8)
            g = int((((int(c) >> 8) & 0xFF) * br) >> 8)
            b = int(((int(c) & 0xFF) * br) >> 8)
            ar[i] = (g<<16) | (r<<8) | b    
            self.sm.put(ar[i], 8)

    def __pixelsShowRPi(self):
        self.__syncWait()
        br = self.brightness
        for i,c in enumerate(self.ar):
            r = int((((int(c) >> 16) & 0xFF) * br) >> 8)
            g = int((((int(c) >> 8) & 0xFF) * br) >> 8)
            b = int(((int(c) & 0xFF) * br) >> 8)
            self.strip.setPixelColor(i, (r<<16) | (g<<8) | b)
        self.strip.show()
   
    def __syncWait(self):
        while self.ticks_ms() < (self.lastFrame_ms + 1000 // self.rateLimit):
            continue
        self.lastFrame_ms = self.ticks_ms()
    
    def __ticks_ms_Linux(self):
        return time.time()*1000
          

    ## @brief Pushes the internal pixel data buffer to the physical GlowBit LEDs
    # 
    # This function must be called before the connected GlowBit LEDs will change colour.
    # 
    # Note that several GlowBit library methods call this method unconditionally (eg: glowbit.blankDisplay ) or optionally (eg: by passing the update = True parameter to stick.graph1D() )
    def pixelsShow(self):
        return

    ## @brief Sets the i'th GlowBit LED to a 32-bit GlowBit colour value.
    # 
    # NB: For efficiency, this method does not do any bounds checking. If the value of the parameter i is larger than the number of LEDs it will cause an IndexError exception.
    #
    # \param i An LED's index
    # \param colour The 32-bit GlowBit colour value

    @micropython.viper
    def pixelSet(self, i: int, colour: int):
        self.ar[i] = colour
    
    ## @brief Sets the i'th GlowBit LED to a 32-bit GlowBit colour value and updates the physical LEDs.
    # 
    # NB: For efficiency, this method does not do any index bounds checking. If the value of the parameter i is larger than the number of LEDs it will cause an IndexError exception.
    #
    # \param i An LED's index
    # \param colour The 32-bit GlowBit colour value

    @micropython.viper
    def pixelSetNow(self, i: int, colour: int):
        self.ar[i] = colour
        self.pixelsShow()
        
    ## @brief Adds a 32-bit GlowBit colour value to the i'th LED in the internal buffer only.
    #
    # Data colour corruption will occur if the sum result of any RGB value exceeds 255. Care must be taken to avoid this manually. eg: if the blue channel's resulting intensity value is 256 it will be set to zero and the red channel incremented by 1. See the colourFunctions class documentation for the 32-bit GlowBit colour specification.
    #
    # NB: For efficiency, this method does not do any index bounds checking. If the value of the parameter i is larger than the number of LEDs it will cause an IndexError exception.
    #
    # \param i An LED's index
    # \param colour The 32-bit GlowBit colour value
    # 

    @micropython.viper
    def pixelAdd(self, i: int, colour: int):
        tmp = int(self.ar[i]) + colour
        self.ar[i] = tmp
            
    ## @brief Fills all pixels with a solid colour value
    #
    # \param colour The 32-bit GlowBit colour value

    @micropython.viper
    def pixelsFill(self, colour: int):
        ar = self.ar
        for i in range(int(len(self.ar))):
            ar[i] = colour
            
    ## @brief Fills all pixels with a solid colour value and updates the physical LEDs.
    #
    # \param colour The 32-bit GlowBit colour value

    @micropython.viper
    def pixelsFillNow(self, colour: int):
        ar = ptr32(self.ar)
        for i in range(int(len(self.ar))):
            ar[i] = colour
        self.pixelsShow()
        
    ## @brief Blanks the entire GlowBit display. ie: sets the colour value of all GlowBit LEDs to zero in the internal buffer and updates the physical LEDs.
    #
    #

    @micropython.viper
    def blankDisplay(self):
        ar = self.ar
        for i in range(int(len(self.ar))):
            ar[i] = 0
        self.pixelsShow()
  

    ## @brief Returns the 32-bit GlowBit colour value of the i'th LED
    #
    # \param i The index of the LED
    # \return The 32-bit GlowBit colour value of the i'th LED

    def getPixel(self, N):
        return self.ar[N]

    ## @brief Sets a new value for the GlowBit display's frames per second (FPS) limiter.
    #
    # \param rateLimitFPS An integer in units of frames per second.

    def updateRateLimitFPS(self, rateLimitFPS):
        self.rateLimit = rateLimitFPS

    ## @brief Sets random colour values on every LED on the attached GlowBit display. This function is blocking, it does not return until the number of frames specified in the iters parameter have been drawn.
    #
    # \param iters The number of frames to draw.

    def chaos(self, iters = 100):
        import random
        ar = self.ar
        while iters > 0:
            for i in range(int(self.numLEDs)):
                ar[i] = int(random.randint(0, 0xFFFFFF))
            self.pixelsShow()
            iters -= 1
        self.blankDisplay()

## @brief Methods specific to 2D matrix displays and tiled arrangements thereof.

class glowbitMatrix(glowbit):

    ## @brief Sets the colour value of the GlowBit LED at a given x-y coordinate
    #
    # The coordinate assumes an origin in the upper left of the display with x increasing to the right and y increasing downwards.
    #
    # If the x-y coordinate falls outside the display's boundary this function will "wrap-around". For example, A dot placed just off the right edge will appear along the left edge.
    #
    # \param x The x coordinate of the GlowBit LED. x must be an integer.
    # \param y The y coordinate of the GlowBit LED. y must be an integer.
    # \param colour A packed 32-bit GlowBit colour value

    @micropython.viper
    def pixelSetXY(self, x: int, y: int, colour: int):
        x = x % int(self.numLEDsX)
        y = y % int(self.numLEDsY)
        self.ar[int(self.remap(x,y))] = colour
   
    ## @brief Sets the colour value of the GlowBit LED at a given x-y coordinate and immediately calls pixelsShow() to update the physical LEDs.
    #
    # The coordinate assumes an origin in the upper left of the display with x increasing to the right and y increasing downwards.
    #
    # If the x-y coordinate falls outside the display's boundary this function will "wrap-around". For example, A dot placed just off the right edge will appear along the left edge.
    #
    # \param x The x coordinate of the GlowBit LED. x must be an integer.
    # \param y The y coordinate of the GlowBit LED. y must be an integer.
    # \param colour A packed 32-bit GlowBit colour value

    @micropython.viper
    def pixelSetXYNow(self, x: int, y: int, colour: int):
        x = x % int(self.numLEDsX)
        y = y % int(self.numLEDsY)
        i = int(self.remap(x,y))
        self.ar[i % int(self.numLEDs)] = colour
        self.pixelsShow()
    
    ## @brief Sets the colour value of the GlowBit LED at a given x-y coordinate
    #
    # The coordinate assumes an origin in the upper left of the display with x increasing to the right and y increasing downwards.
    #
    # If the x-y coordinate falls outside the display's boundary the display's internal buffer will not be modified. 
    #
    # \param x The x coordinate of the GlowBit LED. x must be an integer.
    # \param y The y coordinate of the GlowBit LED. y must be an integer.
    # \param colour A packed 32-bit GlowBit colour value
 
    @micropython.viper
    def pixelSetXYClip(self, x: int, y: int, colour: int):
        if x >= 0 and y >= 0 and x < int(self.numLEDsX) and y < int(self.numLEDsY):
            self.ar[int(self.remap(x,y))] = colour

    ## @brief Adds the colour value to the GlowBit LED at a given (x,y) coordinate
    #
    # The coordinate assumes an origin in the upper left of the display with x increasing to the right and y increasing downwards.
    #
    # If the x-y coordinate falls outside the display's boundary this function will "wrap-around". For example, A dot placed just off the right edge will appear along the left edge.
    #
     # Data colour corruption will occur if the sum result of any RGB value exceeds 255. Care must be taken to avoid this manually. eg: if the blue channel's resulting intensity value is 256 it will be set to zero and the red channel incremented by 1. See the colourFunctions class documentation for the 32-bit GlowBit colour specification.
    #
    # \param x The x coordinate of the GlowBit LED. x must be an integer.
    # \param y The y coordinate of the GlowBit LED. y must be an integer.
    # \param colour A packed 32-bit GlowBit colour value

    @micropython.viper
    def pixelAddXY(self, x: int, y: int, colour: int):
        x = x % int(self.numLEDsX)
        y = y % int(self.numLEDsY)
        i = int(self.remap(x,y))
        self.ar[i] = int(self.ar[i]) + colour

    ## @brief Adds the colour value to the GlowBit LED at a given (x,y) coordinate
    #
    # The coordinate assumes an origin in the upper left of the display with x increasing to the right and y increasing downwards.
    #
    # If the x-y coordinate falls outside the display's boundary the display's internal buffer will not be modified. 
    #
     # Data colour corruption will occur if the sum result of any RGB value exceeds 255. Care must be taken to avoid this manually. eg: if the blue channel's resulting intensity value is 256 it will be set to zero and the red channel incremented by 1. See the colourFunctions class documentation for the 32-bit GlowBit colour specification.
    #
    # \param x The x coordinate of the GlowBit LED. x must be an integer.
    # \param y The y coordinate of the GlowBit LED. y must be an integer.
    # \param colour A packed 32-bit GlowBit colour value

    @micropython.viper
    def pixelAddXYClip(self, x: int, y: int, colour: int):
        if x >= 0 and y >= 0 and x < int(self.numLEDsX) and y < int(self.numLEDsY):
            self.ar[int(self.remap(x,y))] = colour + int(self.ar[int(self.remap(x,y))])
   
    ## @brief Returns the 32-bit GlowBit colour value of the LED at a given (x,y) coordinate
    #
    # If the (x,y) coordinate falls outside of the display's boundary an IndexError exception may be thrown or the GlowBit colour value of an undefined pixel may be returned.
    #
    # \param i The index of the LED
    # \return The 32-bit GlowBit colour value of the i'th LED

    def getPixelXY(self, x, y):
        return self.ar[remap(x,y)]

    ## @brief Draws a straight line between (x0,y0) and (x1,y1) in the specified 32-bit GlowBit colour.
    #
    # If the line is drawn off the screen the "clipping" effect will be inherited from the behaviour of pixelSetXYClip()
    #

    @micropython.viper
    def drawLine(self, x0: int, y0: int, x1: int, y1: int, colour: int):
        steep = abs(y1-y0) > abs(x1-x0)
        
        if steep:
            # Swap x/y
            tmp = x0
            x0 = y0
            y0 = tmp
            
            tmp = y1
            y1 = x1
            x1 = tmp
        
        if x0 > x1:
            # Swap start/end
            tmp = x0
            x0 = x1
            x1 = tmp
            tmp = y0
            y0 = y1
            y1 = tmp
        
        dx = x1 - x0;
        dy = int(abs(y1-y0))
        
        err = dx >> 1 # Divide by 2
        
        if(y0 < y1):
            ystep = 1
        else:
            ystep = -1
            
        while x0 <= x1:
            if steep:
                self.pixelSetXYClip(y0, x0, colour)
            else:
                self.pixelSetXYClip(x0, y0, colour)
            err -= dy
            if err < 0:
                y0 += ystep
                err += dx
            x0 += 1
        
    def drawTriangle(self, x0,y0, x1, y1, x2, y2, colour):
        self.drawLine(x0, y0, x1, y1, colour)
        self.drawLine(x1, y1, x2, y2, colour)
        self.drawLine(x2, y2, x0, y0, colour)
        
    def drawRectangle(self, x0, y0, x1, y1, colour):
        self.drawLine(x0, y0, x1, y0, colour)
        self.drawLine(x1, y0, x1, y1, colour)
        self.drawLine(x1, y1, x0, y1, colour)
        self.drawLine(x0, y1, x0, y0, colour)
    
    @micropython.viper
    def drawRectangleFill(self, x0: int, y0: int, x1: int, y1: int, colour):
        for x in range(x0, x1+1):
            for y in range(y0, y1+1):
                self.pixelSetXY(x,y,colour)
    
    def drawCircle(self, x0, y0, r, colour):
        f = 1-r
        ddf_x = 1
        ddf_y = -2*r
        x = 0
        y = r
        self.pixelSetXYClip(x0, y0 + r, colour)
        self.pixelSetXYClip(x0, y0 - r, colour)
        self.pixelSetXYClip(x0 + r, y0, colour)
        self.pixelSetXYClip(x0 - r, y0, colour)
        
        while x < y:
            if f >= 0: 
                y -= 1
                ddf_y += 2
                f += ddf_y
            x += 1
            ddf_x += 2
            f += ddf_x
            self.pixelSetXYClip(x0 + x, y0 + y, colour)
            self.pixelSetXYClip(x0 - x, y0 + y, colour)
            self.pixelSetXYClip(x0 + x, y0 - y, colour)
            self.pixelSetXYClip(x0 - x, y0 - y, colour)
            self.pixelSetXYClip(x0 + y, y0 + x, colour)
            self.pixelSetXYClip(x0 - y, y0 + x, colour)
            self.pixelSetXYClip(x0 + y, y0 - x, colour)
            self.pixelSetXYClip(x0 - y, y0 - x, colour)
    
    class graph1D(colourFunctions, colourMaps):
        def __init__(self, originX = 0, originY = 7, length = 8, direction = "Up", minValue=0, maxValue=255, colour = 0xFFFFFF, colourMap = "Solid", update = False):
            self.minValue = minValue
            self.maxValue = maxValue
            self.originX = originX
            self.originY = originY
            self.length = length

            self.orientation = -1
            self.inc = 0
            if direction == "Up":
                self.orientation = 1
                self.inc = -1 # Y decreases towards the top
            if direction == "Down":
                self.orientation = 1
                self.inc = 1 # Y increases down
            if direction == "Left":
                self.orientation = 0
                self.inc = -1
            if direction == "Right":
                self.orientation = 0
                self.inc = 1
            
            if self.orientation == -1 or self.inc == 0:
                print("Invalid direction \"", direction, "\".")
                print("Valid options: Up, Down, Left, Right")
                print("Defaulting to Up")
                self.orientation = 1
                self.inc = 1

            self.m = (length)/(maxValue-minValue)
            self.update = update
            self.colour = colour

            if callable(colourMap) == True:
                self.colourMap = colourMap
            elif colourMap == "Solid":
                self.colourMap = self.colourMapSolid
            elif colourMap == "Rainbow":
                self.colourMap = self.colourMapRainbow
                
    def updateGraph1D(self, graph, value):
        N = int(graph.m*(value - graph.minValue))

        m = graph.colourMap
        if graph.orientation == 1:
            n = 0
            for idxY in range(graph.originY, graph.originY+graph.inc*(graph.length), graph.inc):
                #print(N, n, idxY, graph.originY, graph.originY+graph.inc*(graph.length))
                if n < N:
                    self.pixelSetXY(graph.originX, idxY, m(idxY, graph.originY, graph.originY+(graph.inc*graph.length-1)))
                else:
                    self.pixelSetXY(graph.originX, idxY, 0)
                n += 1

        if graph.orientation == 0:
            n = 0
            for idxX in range(graph.originX, graph.originX+graph.inc*(graph.length), graph.inc):
                if n < N:
                    self.pixelSetXY(idxX, graph.originY, m(idxX, graph.originX, graph.originX+(graph.inc*graph.length-1)))
                else:
                    self.pixelSetXY(idxX, graph.originY, 0)
                n += 1

        if graph.update == True:
            self.pixelsShow()

    class graph2D(colourFunctions, colourMaps):
        def __init__(self, minValue=0, maxValue=255, originX = 0, originY = 7, width = 8, height = 8, colour = 0xFFFFFF, bgColour = 0x000000, colourMap = "Solid", update = False, filled = False, bars = False):
            self.minValue = minValue
            self.maxValue = maxValue
            self.originX = originX
            self.originY = originY
            self.width = width
            self.height = height
            self.colour = colour
            self.bgColour = bgColour
            self.update = update
            self.m = (1-height)/(maxValue-minValue)
            self.offset = originY-self.m*minValue
            self.bars = bars
            
            self.data = []
            
            if callable(colourMap) == True:
                self.colourMap = colourMap
            elif colourMap == "Solid":
                self.colourMap = self.colourMapSolid
            elif colourMap == "Rainbow":
                self.colourMap = self.colourMapRainbow
            
        def addData(self, value):
            self.data.insert(0,value)
            if len(self.data) > self.width:
                self.data.pop()
    
    def updateGraph2D(self, graph):
        x = graph.originX+graph.width-1
        m = graph.colourMap
        self.drawRectangleFill(graph.originX, graph.originY-graph.height+1, graph.originX+graph.width-1, graph.originY, graph.bgColour)
        for value in graph.data:
            y = round(graph.m*value + graph.offset)# + graph.originY
            if graph.bars == True:
                for idx in range(y, graph.originY+1):
                    if x >= graph.originX and x < graph.originX+graph.width and idx <= graph.originY and idx > graph.originY-graph.height:
                        self.pixelSet(self.remap(x,idx), m(idx, graph.originY, graph.originY+graph.height-1))
            else:
                if x >= graph.originX and x < graph.originX+graph.width and y <= graph.originY and y > graph.originY+graph.height:
                    self.pixelSet(self.remap(x,y), m(y - graph.originY, graph.originY, graph.originY+graph.height-1))
            x -= 1
        if graph.update == True:
            self.pixelsShow()

                      
    def lineDemo(self, iters = 10):
        self.blankDisplay()
        while iters > 0:
            for x in range(self.numLEDsX):
                self.pixelsFill(0)
                self.drawLine(x, 0, self.numLEDsX-x-1, self.numLEDsY-1, self.rgb2GBColour(255,255,255))
                self.pixelsShow()
            for x in range(self.numLEDsX-2, 0, -1):
                self.pixelsFill(0)
                self.drawLine(x, 0, self.numLEDsX-x-1, self.numLEDsY-1, self.rgb2GBColour(255,255,255))
                self.pixelsShow()
            iters -= 1
        self.blankDisplay()
            
    def fireworks(self, iters = 10):
        self.blankDisplay()
        import random
        while iters > 0:
            self.pixelsFill(0)
            colour = random.randint(0, 0xFFFFFF)
            Cx = random.randint(0, self.numLEDsX-1)
            Cy = random.randint(0, self.numLEDsY-1)
            for r in range(self.numLEDsX//2):
                self.drawCircle(Cx, Cy, r, colour)
                self.pixelsShow()
            for r in range(self.numLEDsX//2):
                self.drawCircle(Cx, Cy, r, 0)
                self.pixelsShow()
            iters -= 1
    
    @micropython.viper
    def circularRainbow(self):
        self.blankDisplay()
        maxX = int(self.numLEDsX)
        maxY = int(self.numLEDsY)
        ar = self.ar
        pixelSetXY = self.pixelSetXY
        wheel = self.wheel
        show = self.pixelsShow
        for colourOffset in range(255):
            for x in range(maxX):
                for y in range(maxY):
                    temp1 = (x-((maxX-1) // 2))
                    temp1 *= temp1
                    temp2 = (y-((maxY-1) // 2))
                    temp2 *= temp2
                    r2 = temp1 + temp2
                    # Square root estimate
                    r = 5
                    r = (r + r2//r) // 2
                    pixelSetXY(x,y,wheel((r*300)//maxX - colourOffset*10))
            show()

    class raindrop():
        def __init__(self, x, speed):
            self.x = x
            self.speed = speed
            self.y = 0
        
        def update(self):
            self.y += self.speed
            return (self.x, (self.y//10))
        
        def getY(self):
            return (self.y//10)

    def rain(self, iters = 1000, density=1):
        import random
        self.blankDisplay()
        drops = []
        toDel = []
        c1 = self.rgb2GBColour(200,255,200)
        c2 = self.rgb2GBColour(0,127,0)
        c3 = self.rgb2GBColour(0,64,0)
        c4 = self.rgb2GBColour(0,32,0)
        c5 = self.rgb2GBColour(0,16,0)
        iter = 0
        p = random.randint(0,self.numLEDsX)
        drops.append(self.raindrop(p, random.randint(2,round(self.numLEDsX))))
        while len(drops) > 0:
            while len(drops)/(density) < self.numLEDs/16 and iters > 0:
                p = random.randint(0,self.numLEDsX)
                drops.append(self.raindrop(p, random.randint(2,round(self.numLEDsX))))
            '''
            Optimised the fill out by just making sure the last pixel drawn in a drop is zero
            '''
            for drop in drops:
                (x,y) = drop.update()
                py = y
                self.pixelSetXYClip(x,y, c1)
                self.pixelSetXYClip(x,y-1, c2)
                self.pixelSetXYClip(x,y-2, c3)
                self.pixelSetXYClip(x,y-3, c4)
                self.pixelSetXYClip(x,y-4, c5)
                self.pixelSetXYClip(x,y-5, 0)
                self.pixelSetXYClip(x,y-6, 0)
                self.pixelSetXYClip(x,y-7, 0)

            for drop in reversed(drops):
                if drop.getY() > self.numLEDsY+6:
                    drops.remove(drop)

            iters -= 1
            self.pixelsShow();

    def textDemo(self, text = "Scrolling Text Demo"):
        self.blankDisplay()
        self.addTextScroll(text)
        while self.scrollingText:
            self.updateTextScroll()
            self.pixelsShow()

    def bounce(self, iters = 1000):
        import random
        Px = random.randint(0, self.numLEDsX-1)
        Py = random.randint(0, self.numLEDsY-1)
        dirY = 1
        dirX = 1

        while iters > 0:
            self.pixelSetXY(Px, Py, 0)
            Px += dirX
            Py += dirY
            self.pixelSetXY(Px, Py, self.wheel(iters%255))
            if Px == 0 or Px == self.numLEDsX-1:
                dirX *= -1
            if Py == 0 or Py == self.numLEDsY-1:
                dirY *= -1
            iters -= 1
            self.pixelsShow()

class stick(glowbit):
    def __init__(self, numLEDs = 8, pin = 18, brightness = 20, rateLimitFPS = 30, sm = 0):
        if _SYSNAME == 'rp2':
            self.sm = rp2.StateMachine(sm, self.__ws2812, freq=8_000_000, sideset_base=Pin(pin))
            self.sm.active(1)
            self.pixelsShow = self.__pixelsShowPico
            self.ticks_ms = time.ticks_ms

        self.numLEDs = numLEDs

        if _SYSNAME == 'Linux':
            self.strip = ws.PixelStrip(numLEDs, pin)
            self.strip.begin()
            self.pixelsShow = self.__pixelsShowRPi
            self.ticks_ms = self.ticks_ms_Linux

        self.lastFrame_ms = self.ticks_ms()

        self.ar = array.array("I", [0 for _ in range(self.numLEDs)])
        self.dimmer_ar = array.array("I", [0 for _ in range(self.numLEDs)])
        if rateLimitFPS > 0: 
            self.rateLimit = rateLimitFPS
        else:
            self.rateLimit = 100
        
        if brightness <= 1.0 and isinstance(brightness, float):
            self.brightness = int(brightness*255)
        else:
            self.brightness = int(brightness)
        
        self.pixelsFill(0)
        self.pixelsShow()
        
        self.pulses = []

    class pulse(colourFunctions, colourMaps):
        def __init__(self, speed = 100, colour = 0xFFFFFF, index = 0, colourMap = None):
            self.speed = speed
            self.index = index
            self.position = self.index*100 # index * 100
           
            if type(colour) is list:
                self.colour = colour
            else:
                self.colour = [colour]

            if callable(colourMap) == True:
                self.colourMap = colourMap
            elif colourMap == "Solid":
                self.colourMap = self.colourMapSolid
            elif colourMap == "Rainbow":
                self.colourMap = self.colourMapRainbow
            else:
                self.colourMap = None
            
        def update(self):
            self.position += self.speed
            self.index = self.position//100
 
    def addPulse(self, speed = 100, colour = [0xFFFFFF], index = 0, colourMap = None):
        self.pulses.append(self.pulse(speed, colour, index, colourMap))
        
    def updatePulses(self):
        self.pixelsFill(0)
        for p in self.pulses:
            i = p.index
            
            for c in p.colour:
                if c == -1:
                    if callable(p.colourMap):
                        c = p.colourMap(i, 0, self.numLEDs)
                    else:
                        c = 0
                if i >=0 and i < self.numLEDs:
                    self.pixelAdd(i, c)
                i -= 1
            p.update()
            
        for p in reversed(self.pulses):
            if p.index - len(p.colour) >= self.numLEDs:
                self.pulses.remove(p)
            if p.index + len(p.colour) < 0:
                self.pulses.remove(p)
        
    class graph1D(colourFunctions, colourMaps):
        def __init__(self, minValue=0, maxValue=255, minIndex = 0, maxIndex = 7, colour = 0xFFFFFF, colourMap = "Solid", update = False):
            self.minValue = minValue
            self.maxValue = maxValue
            self.minIndex = minIndex
            self.maxIndex = maxIndex
            self.m = (maxIndex-minIndex)/(maxValue-minValue)
            self.offset = minIndex-self.m*minValue
            self.update = update
            self.colour = colour

            if callable(colourMap) == True:
                self.colourMap = colourMap
            elif colourMap == "Solid":
                self.colourMap = self.colourMapSolid
            elif colourMap == "Rainbow":
                self.colourMap = self.colourMapRainbow
    
    def updateGraph1D(self, graph, value):
        i = int(graph.m*value + graph.offset)
        m = graph.colourMap
        for idx in range(graph.minIndex, i+1):
            self.pixelSet(idx, m(idx, graph.minIndex, graph.maxIndex))
        for idx in range(i+1, graph.maxIndex+1):
            self.pixelSet(idx, 0)
        if graph.update == True:
            self.pixelsShow()
        
               
    def fillSlice(self, i=0, j=-1, colour = 0xFFFFFF):
        if j == -1:
            j = self.numLEDs
        for k in range(i, j+1):
            self.pixelSet(k, colour)

    def pulseDemo(self, iters = 480):
        while iters > 0:
            if iters % (self.numLEDs+4) == 0:
                if iters % (2*(self.numLEDs+4)) == 0:
                    self.addPulse()
                else:
                    self.addPulse(speed=-100, index=self.numLEDs, colourMap="Rainbow", colour=[-1, self.rgb2GBColour(255,255,255), -1])
            self.pixelsFill(0)
            self.updatePulses()
            self.pixelsShow()
            iters -= 1

    def graphDemo(self, iters = 3):
        g1 = stick.graph1D(minIndex = 0, maxIndex = 7, minValue=1, maxValue=8, update=True, colourMap = "Rainbow")
        g2 = stick.graph1D(minIndex = 0, maxIndex = 7, minValue=1, maxValue=8, update=True, colourMap = "Solid")
        while iters > 0:
            for x in range(1,9):
                self.updateGraph1D(g1, x)
            for x in range(8,-1, -1):
                self.updateGraph1D(g1, x)
            for x in range(1,9):
                self.updateGraph1D(g2, x)
            for x in range(8,-1, -1):
                self.updateGraph1D(g2, x)

            iters -= 1

    def sliceDemo(self):
        iters = 3
        colour = 0xFF0000
        while iters > 0:
            for i in range(self.numLEDs):
                self.pixelsFill(0)
                self.fillSlice(0, i, colour)
                self.pixelsShow()
            for i in range(self.numLEDs):
                self.pixelsFill(0)
                self.fillSlice(i, self.numLEDs-1, colour)
                self.pixelsShow()
            colour = colour >> 8
            iters -= 1

        self.pixelsFill(0)
        self.pixelsShow()

class rainbow(stick):
    def __init__(self, numLEDs = 13, pin = 18, brightness = 40, rateLimitFPS = 60, sm = 0):
        super().__init__(numLEDs, pin, brightness, rateLimitFPS, sm)
        self.drawRainbow()

    def pixelSetAngle(self, angle, colour):
        self.pixelSet(angle//15, colour)

    def drawRainbow(self, offset = 0):
        colPhase = offset
        for i in range(self.numLEDs):
            self.pixelSet(i, self.wheel(colPhase%255))
            colPhase += 17 # "True" rainbow, red to purple
        self.pixelsShow()
    
    def rainbowLoop(self):
        x = 0
        while True:
            self.drawRainbow(x)
            x += 1

class triangle(glowbit):
    def __init__(self, numTris = 1, pin = 18, brightness = 20, rateLimitFPS = -1, sm = 0, LEDsPerTri = 6):
        if _SYSNAME == 'rp2':
            self.sm = rp2.StateMachine(sm, self.__ws2812, freq=8_000_000, sideset_base=Pin(pin))
            self.sm.active(1)
            self.pixelsShow = self.__pixelsShowPico
            self.ticks_ms = time.ticks_ms

        self.LEDsPerTri = LEDsPerTri
        self.numLEDs = numTris*LEDsPerTri
        self.numTris = numTris

        if _SYSNAME == 'Linux':
            self.strip = ws.PixelStrip(self.numLEDs, pin)
            self.strip.begin()
            self.pixelsShow = self.__pixelsShowRPi
            self.ticks_ms = self.ticks_ms_Linux

        self.ar = array.array("I", [0 for _ in range(self.numLEDs)])
        self.dimmer_ar = array.array("I", [0 for _ in range(self.numLEDs)])
        
        if rateLimitFPS > 0: 
            self.rateLimit = rateLimitFPS
        else:
            self.rateLimit = 100
        
        if brightness <= 1.0 and isinstance(brightness, float):
            self.brightness = int(brightness*255)
        else:
            self.brightness = int(brightness)
        
        self.pixelsFill(0)
        self.lastFrame_ms = self.ticks_ms()
        self.pixelsShow()
                
    def fillTri(self, tri, colour):
        # Fills all N leds on triangle Y
        addr = self.LEDsPerTri*tri
        for i in range(addr, addr+self.LEDsPerTri):
            self.ar[i] = colour

class matrix4x4(glowbitMatrix):
    def __init__(self, tiles = 1, pin = 18, brightness = 20, mapFunction = None, rateLimitFPS = 30, sm = 0):
        if _SYSNAME == 'rp2':
            self.sm = rp2.StateMachine(sm, self.__ws2812, freq=8_000_000, sideset_base=Pin(pin))
            self.sm.active(1)
            self.pixelsShow = self.__pixelsShowPico
            self.ticks_ms = time.ticks_ms

        self.tiles = tiles
        self.numLEDs = tiles*16
        self.numLEDsX = tiles*4
        self.numLEDsY = 4

        if _SYSNAME == 'Linux':
            self.strip = ws.PixelStrip(self.numLEDs, pin)
            self.strip.begin()
            self.pixelsShow = self.__pixelsShowRPi
            self.ticks_ms = self.ticks_ms_Linux

        self.ar = array.array("I", [0 for _ in range(self.numLEDs)])
        self.dimmer_ar = array.array("I", [0 for _ in range(self.numLEDs)])
        self.lastFrame_ms = self.ticks_ms()
        self.scrollingText = False # Only required because the self.pixelsShow() function is shared with the 8x8
        
        if brightness <= 1.0 and isinstance(brightness, float):
            self.brightness = int(brightness*255)
        else:
            self.brightness = int(brightness)
        
        if mapFunction is not None:
            self.remap = mapFunction
            print(self.remap)
        else:
            self.remap = self.remap4x4
            
        if rateLimitFPS > 0: 
            self.rateLimit = rateLimitFPS
        else:
            self.rateLimit = 100
            
        # Blank display
        self.pixelsFill(0)
        self.pixelsShow()
        self.pixelsShow() # On fresh power-on this is needed twice. Why?!?!

    @micropython.viper
    def remap4x4(self, x: int,y: int) -> int:
        mc = x // 4 # Module col that x falls into
        mx = x - 4*mc # Module x position - inside sub-module, relative to (0,0) top left
        TopLeftIndex = mc * 16 # ASSUMES 4X4 MODULES
        LEDsBefore = 4*y + x - 4*mc # LEDs before in a module
        return TopLeftIndex + LEDsBefore
      
class matrix8x8(glowbitMatrix):
    def __init__(self, tileRows = 1, tileCols = 1, pin = 18, brightness = 20, mapFunction = None, rateLimitFPS = -1, rateLimitCharactersPerSecond = -1, sm = 0):
    
        self.tileRows = tileRows
        self.tileCols = tileCols
        self.numLEDs = tileRows*tileCols*64
        self.numLEDsX = tileCols*8
        self.numLEDsY = tileRows*8
        
        if _SYSNAME == 'rp2':
            self.sm = rp2.StateMachine(sm, self.__ws2812, freq=8_000_000, sideset_base=Pin(pin))
            self.sm.active(1)
            self.pixelsShow = self.__pixelsShowPico
            self.ticks_ms = time.ticks_ms

        if _SYSNAME == 'Linux':
            self.strip = ws.PixelStrip(self.numLEDs, pin)
            self.strip.begin()
            self.pixelsShow = self.__pixelsShowRPi
            self.ticks_ms = self.ticks_ms_Linux

        self.ar = array.array("I", [0 for _ in range(self.numLEDs)])
        self.dimmer_ar = array.array("I", [0 for _ in range(self.numLEDs)])
#        self.text_ar = array.array("I", [0 for _ in range(self.numLEDs)])
        
        if brightness <= 1.0 and isinstance(brightness, float):
            self.brightness = int(brightness*255)
        else:
            self.brightness = int(brightness)
            
        self.scrollingText = False
        
        self.lastFrame_ms = self.ticks_ms()
        
        if rateLimitFPS > 0: 
            self.rateLimit = rateLimitFPS
        elif rateLimitCharactersPerSecond > 0:
            self.rateLimit = rateLimitCharactersPerSecond * 8
        else:
            self.rateLimit = 30
        
        self.scrollingTextList = []
        
        if mapFunction is not None:
            self.remap = mapFunction
            print(self.remap)
        else:
            self.remap = self.remap8x8
            
        # Blank display
        self.blankDisplay()

    def printTextWrap(self, string, x = 0, y = 0, colour = 0xFFFFFF):
        Px = x
        Py = y
        for char in string:
            if Py < self.numLEDsY - 7:
                self.drawChar(char, Px, Py, colour)
            Px += 8
            if Px + 1 >= self.numLEDsX:
                Py += 8
                if x < 0:
                    Px = 0
                else:
                    Px = x

    class textScroll():
        def __init__(self, string, y = 0, x = 0, colour = 0xFFFFFF, bgColour = 0):
            self.x = x
            self.y = y
            self.colour = colour
            self.bgColour = bgColour
            self.string = string
        
    def addTextScroll(self, string, y = 0, x = 0, colour = 0xFFFFFF, bgColour = 0x000000, update=False, blocking=False):
        self.scrollingTextList.append(self.textScroll(string, y, -self.numLEDsX-x, colour, bgColour))
        self.updateText = update
        self.scrollingText = True
        if blocking == True:
            # Force self-updating when doing a blocking print
            if self.updateText == False:
                print("Ignoring update=False for blocking call to printTextScroll()")
                self.update = True
            while self.scrollingText > 0:
                self.updateTextScroll()
         
    def updateTextScroll(self):
        for textLine in self.scrollingTextList:
            x = 0
            
            self.drawRectangleFill(0,textLine.y,self.numLEDsX, textLine.y+7, textLine.bgColour)
            for c in textLine.string:
                self.drawChar(c, -textLine.x+8*x, textLine.y, textLine.colour)
                x += 1
            textLine.x += 1
                            
        for textLine in reversed(self.scrollingTextList):
            if textLine.x == 8*len(textLine.string):
                self.scrollingTextList.remove(textLine)
        
        if self.updateText == True:
            self.pixelsShow()
        if len(self.scrollingTextList) == 0:
            self.scrollingText = False
         
    @micropython.viper
    def remap8x8(self, x: int,y: int) -> int:
        #mr = (y // 8) # Module row that y falls into
        #mc = (x // 8) # Module col that x falls into
        #mx = (x - 8*mc) # Module x position - inside sub-module, relative to (0,0) top left
        #my = (y - 8*mr) # Module y position - inside sub-module, relative to (0,0) top left
        if (y//8) % 2 == 0:
            # Module row is even
            return 64*((y//8)*int(self.tileCols) + x//8) + (8*(y%8) + x%8)
        else:
            return 64*((y//8)*int(self.tileCols) + (int(self.tileCols) - x//8 - 1)) + (8*(y%8) + x%8)
        #TopLeftIndex = (ModulesBefore * 64) # ASSUMES 8X8 MODULES
        #LEDsBefore = (8*(y-8*mr) + x-8*mc) # LEDs before in a module
        #return (ModulesBefore * 64) + (8*(y%8) + x%8)
        #return (ModulesBefore * 64) + (8*(y-8*(y//8)) + x-8*(x//8))

    @micropython.viper
    def drawChar(self, char, Px: int, Py: int, colour: int):
        if Px < -7 or Px > int(self.numLEDsX):
            return
        ar = ptr32(self.ar)
        remap = self.remap8x8
        x = Px
        y = Py
        charIdx = (int(ord(char))-32)*8
        N = int(self.numLEDs)
        maxCol = int(min(8, int(self.numLEDsX)-Px))
        if x < 0:
            minCol = -1*x
            x = 0
        else:
            minCol = 0
        tileCols = int(self.tileCols)
        for col in range(minCol, maxCol):
            dat = int(petme128[charIdx + col])
            ar[int(remap(x,y))] += ((dat)&1)*(colour)
            ar[int(remap(x,y+1))] += ((dat>>1)&1)*colour
            ar[int(remap(x,y+2))] += ((dat>>2)&1)*colour
            ar[int(remap(x,y+3))] += ((dat>>3)&1)*colour
            ar[int(remap(x,y+4))] += ((dat>>4)&1)*colour
            ar[int(remap(x,y+5))] += ((dat>>5)&1)*colour
            ar[int(remap(x,y+6))] += ((dat>>6)&1)*colour
            ar[int(remap(x,y+7))] += ((dat>>7)&1)*colour
            x += 1
    
    ## @brief Changes the 8x8 matrix display's update rate in units of "characters of scrolling text per second".
    #
    # For example, a value of 2 would scroll 2 charcters per second; leaving each character at least partly visible for 0.5 seconds.

    def updateRateLimitCharactersPerSecond(self, rateLimitCharactersPerSecond):
        self.rateLimit = rateLimitCharactersPerSecond * 8
