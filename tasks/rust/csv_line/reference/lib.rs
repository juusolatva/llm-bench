pub fn parse_csv_line(line: &str) -> Result<Vec<String>, String> {
    let mut fields = Vec::new();
    let mut chars = line.chars().peekable();
    loop {
        let mut field = String::new();
        if chars.peek() == Some(&'"') {
            chars.next();
            loop {
                match chars.next() {
                    None => return Err("unterminated quoted field".to_string()),
                    Some('"') if chars.peek() == Some(&'"') => {
                        chars.next();
                        field.push('"');
                    }
                    Some('"') => break,
                    Some(c) => field.push(c),
                }
            }
            match chars.next() {
                None => {
                    fields.push(field);
                    return Ok(fields);
                }
                Some(',') => fields.push(field),
                Some(c) => return Err(format!("unexpected {:?} after quoted field", c)),
            }
        } else {
            loop {
                match chars.next() {
                    None => {
                        fields.push(field);
                        return Ok(fields);
                    }
                    Some(',') => break,
                    Some('"') => return Err("quote in unquoted field".to_string()),
                    Some(c) => field.push(c),
                }
            }
            fields.push(field);
        }
    }
}
