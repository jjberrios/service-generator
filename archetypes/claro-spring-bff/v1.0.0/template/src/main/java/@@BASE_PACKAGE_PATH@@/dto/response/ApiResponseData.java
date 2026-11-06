package @@BASE_PACKAGE@@.dto.response;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data 
@Builder 
@NoArgsConstructor
@AllArgsConstructor
public class ApiResponseData<T> {

    private ResponseAudit responseAudit;
    private T responseData;
}