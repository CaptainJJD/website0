let time = 0;
let wave = []

function setup() {
  createCanvas(2000,1250);
}

function draw() {
  background(0);
  translate(312, 312);
  let radius = 124;

    stroke(255, 100);
    noFill();
    ellipse(0, 0, radius * 2);
	
	let x = radius * cos(time);
	let y = radius * sin(time);
	wave.push(y);
	noFill();
	line(0, 0, x, y);
	ellipse(x, y, 4);
	
	translate(0, 0,);
	rotate (50, 10);
	

	beginShape();
	for (let i = 0; i < wave.length; i++) {
		vertex(i, wave[i]);
	}
     endShape();
	 

	 
	
  time += 0.09;

}





